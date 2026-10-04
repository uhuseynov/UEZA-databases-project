# MediaWiki Data Model

[← MediaWiki](./Home.md) | [Documentation Home](../../Home.md)

A `WikiArticle` represents a snapshot of an article retrieved from MediaWiki.

## WikiArticle

```python
@dataclass(slots=True, frozen=True)
class WikiArticle:
    page_id: int
    title: str
    text: str
    length: int
    revision_id: int
    last_modified: datetime
    categories: tuple[str, ...]
    links: tuple[str, ...]
```

## Fields

### `page_id`

Stable MediaWiki page identifier, useful independently of the current article title.

### `title`

Canonical article title returned by MediaWiki. It may differ from the requested title after redirect resolution.

### `text`

Raw article content. Cleaning is intentionally deferred to a later ingestion stage.

### `length`

Article length reported by MediaWiki. It can later be stored in MariaDB for relational filtering or analysis.

### `revision_id`

Identifier of the retrieved revision. It can be compared with a stored revision to detect article changes during synchronization.

### `last_modified`

Timestamp of the retrieved revision, useful for synchronization and relational metadata.

### `categories`

MediaWiki categories associated with the article. The client does not decide which categories are useful.

### `links`

Outgoing article links. The client retrieves article-namespace links without deciding whether linked articles belong to the final dataset.

## Immutability

`WikiArticle` is immutable because it represents the state of an article at a particular retrieved revision.

`frozen=True` prevents field reassignment, while tuples prevent mutation of the `categories` and `links` collections.
