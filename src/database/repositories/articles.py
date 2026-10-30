"""Transactional persistence for Wikipedia articles."""

import re
import time
from datetime import UTC

from sqlalchemy import text

from src.rag.retriever import vector_to_text


_VECTOR_KEY = re.compile(r"VECTOR KEY `(?P<name>\w+)` \(`embedding`\)(?P<options>[^\n]*)")
_INDEX_M = re.compile(r"`?M`?\s*=\s*'?(?P<m>\d+)'?")
_INDEX_DISTANCE = re.compile(r"`?DISTANCE`?\s*=\s*'?(?P<distance>[a-z]+)'?")


def vector_index_definition(create_table: str) -> tuple[str, int | None, str | None]:
    """Name, M and distance of the vector index in a SHOW CREATE TABLE statement."""

    match = _VECTOR_KEY.search(create_table)
    if match is None:
        raise ValueError("article_chunks has no vector index on embedding")

    options = match["options"]
    m = _INDEX_M.search(options)
    distance = _INDEX_DISTANCE.search(options)

    m_value = int(m["m"]) if m else None
    if m_value is not None and not 3 <= m_value <= 200:
        raise ValueError(f"unexpected M for the vector index: {m_value}")

    distance_value = distance["distance"] if distance else None
    if distance_value not in (None, "cosine", "euclidean"):
        raise ValueError(f"unexpected distance for the vector index: {distance_value}")

    return match["name"], m_value, distance_value


class ArticleRepository:
    def __init__(self, database):
        self.database = database

    async def replace_article(
        self,
        *,
        wiki,
        csv_row,
        chunks,
        vectors,
    ) -> bool:
        """Atomically replace an article and its related rows.

        Returns True when the article was already stored, so its old chunks were
        deleted and new ones inserted.
        """

        if not chunks:
            raise ValueError("Article must contain chunks")

        if len(chunks) != len(vectors):
            raise ValueError("Chunk and embedding counts do not match")

        if int(csv_row["pageid"]) != wiki.page_id:
            raise ValueError(f"Page ID mismatch for {csv_row['title']}")

        if any(len(vector) != 768 for vector in vectors):
            raise ValueError("Every embedding must contain 768 dimensions")

        # Prepare vector serialization before opening transaction.
        serialized_vectors = [vector_to_text(vector) for vector in vectors]

        async with self.database.get_session() as session:
            existing = await session.execute(
                text("SELECT id FROM articles WHERE page_id = :page_id"),
                {"page_id": wiki.page_id},
            )

            article_id = existing.scalar_one_or_none()
            replaced = article_id is not None

            params = self._article_params(wiki, csv_row)

            if article_id is not None:
                article_id = int(article_id)

                # No ON DELETE CASCADE exists in schema.sql.
                for table in (
                    "article_chunks",
                    "article_categories",
                    "article_links",
                ):
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE article_id = :article_id"),
                        {"article_id": article_id},
                    )

                await session.execute(
                    text("""
                        UPDATE articles
                        SET
                            title = :title,
                            url = :url,
                            root_category = :root_category,
                            article_length = :article_length,
                            revision_id = :revision_id,
                            last_edit_date = :last_edit_date
                        WHERE id = :article_id
                    """),
                    {
                        "article_id": article_id,
                        **params,
                    },
                )

            else:
                result = await session.execute(
                    text("""
                        INSERT INTO articles (
                            page_id,
                            title,
                            url,
                            root_category,
                            article_length,
                            revision_id,
                            last_edit_date
                        )
                        VALUES (
                            :page_id,
                            :title,
                            :url,
                            :root_category,
                            :article_length,
                            :revision_id,
                            :last_edit_date
                        )
                    """),
                    {
                        "page_id": wiki.page_id,
                        **params,
                    },
                )

                article_id = int(result.lastrowid)

            # Store Wikipedia categories.
            for category in dict.fromkeys(wiki.categories):
                await session.execute(
                    text("""
                        INSERT INTO article_categories (
                            article_id,
                            category
                        )
                        VALUES (:article_id, :category)
                    """),
                    {
                        "article_id": article_id,
                        "category": category,
                    },
                )

            # Store outgoing Wikipedia links.
            for link in dict.fromkeys(wiki.links):
                await session.execute(
                    text("""
                        INSERT INTO article_links (
                            article_id,
                            linked_title
                        )
                        VALUES (:article_id, :linked_title)
                    """),
                    {
                        "article_id": article_id,
                        "linked_title": link,
                    },
                )

            # Store chunks and embeddings.
            for index, (chunk, vector) in enumerate(zip(chunks, serialized_vectors, strict=True)):
                await session.execute(
                    text("""
                        INSERT INTO article_chunks (
                            article_id,
                            chunk_index,
                            chunk_text,
                            embedding
                        )
                        VALUES (
                            :article_id,
                            :chunk_index,
                            :chunk_text,
                            VEC_FromText(:embedding)
                        )
                    """),
                    {
                        "article_id": article_id,
                        "chunk_index": index,
                        "chunk_text": chunk,
                        "embedding": vector,
                    },
                )

        return replaced

    @staticmethod
    def _article_params(wiki, csv_row):
        return {
            "title": csv_row["title"],
            "url": (f"https://en.wikipedia.org/?curid={wiki.page_id}"),
            "root_category": csv_row["root_category"],
            "article_length": wiki.length,
            "revision_id": wiki.revision_id,
            "last_edit_date": (wiki.last_modified.astimezone(UTC).replace(tzinfo=None)),
        }

    async def revision_ids(self):
        """Return page_id -> revision_id mapping."""

        async with self.database.get_session() as session:
            result = await session.execute(text("SELECT page_id, revision_id FROM articles"))

            return {int(row[0]): int(row[1]) for row in result.all()}

    async def analyze(self):
        """Refresh database statistics after ingestion."""

        async with self.database.get_session() as session:
            for table in (
                "articles",
                "article_categories",
                "article_links",
                "article_chunks",
            ):
                await session.execute(text(f"ANALYZE TABLE {table}"))

    async def vector_index(self) -> tuple[str, int | None, str | None]:
        """Name, M and distance of the vector index on article_chunks.embedding."""

        async with self.database.get_session() as session:
            row = (await session.execute(text("SHOW CREATE TABLE article_chunks"))).one()
            return vector_index_definition(row[1])

    async def rebuild_vector_index(self, m: int | None = None) -> float:
        """Drop and re-create the vector index, with its current M and distance.

        ``m`` builds it with another M instead (3 to 200, as MariaDB allows).

        After many chunks were deleted and inserted again (a re-ingest), searches
        were three times as slow until the index was rebuilt: deleted vectors stay in
        the graph, which then no longer fits into MariaDB's index cache (see
        docs/database/Index-State.md). Returns the seconds it took.
        """

        if m is not None and (isinstance(m, bool) or not isinstance(m, int) or not 3 <= m <= 200):
            raise ValueError(f"M must be an integer from 3 to 200, got {m!r}")

        async with self.database.get_session() as session:
            row = (await session.execute(text("SHOW CREATE TABLE article_chunks"))).one()
            name, current_m, distance = vector_index_definition(row[1])

            options = ""
            if m is not None or current_m is not None:
                options += f" M={m if m is not None else current_m}"
            if distance is not None:
                options += f" DISTANCE={distance}"

            start = time.perf_counter()
            await session.execute(text(f"ALTER TABLE article_chunks DROP INDEX `{name}`"))
            await session.execute(
                text(f"ALTER TABLE article_chunks ADD VECTOR INDEX `{name}` (embedding){options}")
            )
            await session.execute(text("ANALYZE TABLE article_chunks"))

        await self.refresh_graph_statistics()
        return time.perf_counter() - start

    async def refresh_graph_statistics(self) -> None:
        """Make InnoDB recalculate the statistics of the table that holds the HNSW graph.

        ALTER TABLE ... ADD VECTOR INDEX fills that hidden table without counting the rows
        as modified, so InnoDB keeps the statistics of the empty table (n_rows = 0), and
        ANALYZE TABLE article_chunks does not reach it. After a restart MariaDB takes the
        size of the graph from these statistics, and searches then skip part of the graph
        (measured in docs/database/Index-State.md).

        One inserted and deleted chunk counts as a modification of the graph table, and
        InnoDB then recalculates its statistics in the background within seconds. The
        deleted node stays in the graph, like every deleted chunk until the next rebuild.
        """

        async with self.database.get_session() as session:
            await session.execute(
                text(
                    "INSERT INTO article_chunks (article_id, chunk_index, chunk_text, embedding) "
                    "SELECT article_id, -1, 'statistics refresh', embedding "
                    "FROM article_chunks ORDER BY id LIMIT 1"
                )
            )
        async with self.database.get_session() as session:
            await session.execute(text("DELETE FROM article_chunks WHERE chunk_index = -1"))
