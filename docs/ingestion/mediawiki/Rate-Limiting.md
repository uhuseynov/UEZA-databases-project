# MediaWiki Rate Limiting

[← MediaWiki](./Home.md) | [Documentation Home](../../Home.md)

The MediaWiki integration limits how quickly requests are sent to the public API.

## Purpose

A larger ingestion run can retrieve hundreds of articles. Rate limiting prevents requests from being generated as quickly as the machine and network allow.

## Configuration

```python
MediaWikiClient(
    ...,
    requests_per_second=2.0,
)
```

For two requests per second:

```text
minimum interval = 1 / 2 = 0.5 seconds
```

## Request Flow

```text
request()
   ↓
RateLimiter.wait()
   ↓
interval elapsed?
   ├── no → sleep remaining time
   └── yes
   ↓
HTTP request
```

## Monotonic Time

Elapsed time is measured with a monotonic clock so normal system clock changes do not affect interval measurement.

## Separation from Retry Logic

Rate limiting controls normal request frequency. Retry delays handle temporary failures. These are separate responsibilities.

See [Retry Strategy →](./Retry-Strategy.md).

## Testing

Timing is mocked in unit tests so the suite does not actually wait. Tests verify the first request, subsequent intervals, and remaining wait time.

See [Testing →](./Testing.md).
