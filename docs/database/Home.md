# Database

[← Documentation Home](../Home.md)

The database layer provides infrastructure for connecting the application to MariaDB and managing schema migrations.

## Current Structure

```text
src/database/
├── base.py
├── connection.py
├── migrations/
│   ├── env.py
│   └── script.py.mako
├── models/
├── repositories/
└── service/
```

`models`, `repositories`, and `service` are currently structural placeholders. Database entities and vector-search behavior should be documented when those implementations are added.

## Connection Model

```text
SQLAlchemy AsyncEngine
        ↓
     aiomysql
        ↓
     MariaDB
```

[Connection and Sessions →](./Connection.md)

## Migration Model

```text
Alembic
   ↓
SQLAlchemy synchronous connection
   ↓
PyMySQL
   ↓
MariaDB
```

[Migrations →](./Migrations.md)

## Schema and Vector Search

The schema lives in [`schema.sql`](../../schema.sql): four tables for articles, their categories, their links and the text chunks with their vectors. MariaDB creates it automatically on the first start of an empty database volume. The vector index, its parameters and the way MariaDB plans a search with SQL filters are described in [Vector Search and Index Parameters](./Vector-Search.md). How the speed and the results of the index depend on its history (a rebuild, a restart, replaced chunks) is in [Vector Index State](./Index-State.md).

### Where the columns come from

| Column | Filter name in `docs/data_decisions.md` | Source |
| --- | --- | --- |
| `articles.page_id` | | MediaWiki client: `page_id` |
| `articles.title` | | `title` column of `data/articles.csv` (the ground truth uses these titles) |
| `articles.root_category` | | `root_category` column of `data/articles.csv` (not known to MediaWiki) |
| `articles.article_length` | `article_length` | MediaWiki client: `length` |
| `articles.last_edit_date` | `last_edit_date` | MediaWiki client: `last_modified` |
| `articles.revision_id` | | MediaWiki client: `revision_id` (sync compares it to detect changes) |
| `article_categories.category` | `category` | MediaWiki client: `categories` |
| `article_links.linked_title` | `outgoing_links` | MediaWiki client: `links` |
