"""Transactional persistence for Wikipedia articles."""

from datetime import UTC

from sqlalchemy import text

from src.rag.retriever import vector_to_text


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
    ):
        """Atomically replace an article and its related rows."""

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
