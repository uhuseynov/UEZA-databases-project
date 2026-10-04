# MediaWiki Pagination

[← MediaWiki](./Home.md) | [Documentation Home](../../Home.md)

MediaWiki does not guarantee that all requested metadata is returned in one response. Large articles may require multiple requests for categories or outgoing links.

## Continuation

A response may contain:

```json
{
  "continue": {
    "plcontinue": "233488|0|Example",
    "continue": "||"
  }
}
```

The continuation values are passed into the next request until MediaWiki stops returning continuation information.

## Independent Continuation

Different properties, particularly categories and links, can require continuation independently. The client follows the continuation data supplied by MediaWiki instead of assuming identical pagination behavior.

## Why Pagination Matters

Ignoring continuation can silently create incomplete `WikiArticle` metadata even though the HTTP request itself succeeded.

## Collection and Deduplication

Metadata from continuation responses is collected and combined. Categories and links are deduplicated before the final `WikiArticle` is returned.

## Testing

Mocked responses test continuation, forwarding of continuation parameters, metadata collection, deduplication, and termination.

See [Testing →](./Testing.md).
