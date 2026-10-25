"""Database consistency checks for ingested articles."""

from sqlalchemy import text

from src.ingestion.pipeline import read_articles


async def check_database(
    database,
    csv_path: str = "data/articles.csv",
) -> dict:
    """Validate article coverage and related records."""

    expected = read_articles(csv_path)

    async with database.get_session() as session:
        result = await session.execute(
            text("""
                SELECT id, page_id, title
                FROM articles
            """)
        )

        articles = result.mappings().all()

        actual = {row["title"]: int(row["page_id"]) for row in articles}

        missing = [
            row["title"] for row in expected if actual.get(row["title"]) != int(row["pageid"])
        ]

        # Every article must have sequential chunks.
        result = await session.execute(
            text("""
                SELECT
                    a.title,
                    COUNT(c.id) AS chunk_count,
                    MIN(c.chunk_index) AS first_index,
                    MAX(c.chunk_index) AS last_index
                FROM articles a
                LEFT JOIN article_chunks c
                    ON c.article_id = a.id
                GROUP BY a.id
                HAVING
                    chunk_count = 0
                    OR first_index <> 0
                    OR last_index <> chunk_count - 1
            """)
        )

        bad_chunks = [row[0] for row in result.all()]

        # Verify there are no orphan relationships.
        orphans = {}

        for table in (
            "article_chunks",
            "article_categories",
            "article_links",
        ):
            result = await session.execute(
                text(f"""
                    SELECT COUNT(*)
                    FROM {table} child
                    LEFT JOIN articles a
                        ON a.id = child.article_id
                    WHERE a.id IS NULL
                """)
            )

            orphans[table] = int(result.scalar_one())

    valid = (
        not missing
        and not bad_chunks
        and not any(orphans.values())
        and len(articles) == len(expected)
    )

    return {
        "ok": valid,
        "expected_articles": len(expected),
        "stored_articles": len(articles),
        "missing_articles": missing,
        "invalid_chunks": bad_chunks,
        "orphan_records": orphans,
    }
