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

## Scope of the limit

A `RateLimiter` belongs to the instance, and the limit holds for the clients that share it. In the application the container creates **one limiter per process** (`mediawiki_rate_limiter`, a singleton) and gives it to every client it builds, so all the clients of a process share one limit of `MEDIAWIKI_REQUESTS_PER_SECOND`: the API's per-request clients, and the ingest or sync CLI, which has one client.

It is **per process, not distributed**. Two uvicorn workers have two limiters, so the limit of the service is the rate times the number of workers. An ingest or sync started next to a running API is another process with its own limiter. Nothing coordinates between processes; if that matters, lower the rate or run one worker.

The limiter spaces the *start* of requests only. A request that is already running does not hold up the next one, so slow responses overlap, and only callers that arrive faster than the limit wait for their turn.

## Concurrent API requests

`GET /articles/{title}` creates a client per request (it owns its HTTP connections and is closed afterwards) but shares the limiter and the article cache. The route runs the blocking client in a worker thread, so the event loop never waits for the limiter. To keep a burst of article requests from using up the worker threads that the embedding model and the other routes need, at most `MEDIAWIKI_API_CONCURRENCY` (default 4) requests fetch at the same time; the others wait in the event loop, before any client or thread is created. This is a cap on parallel fetches, not a lock: four fetches still run side by side, and `/search`, `/ask` and `/health` are not affected.

The ingest and sync keep their behaviour and throughput: one client per process, one request stream at the configured rate.

## Monotonic Time

Elapsed time is measured with a monotonic clock so normal system clock changes do not affect interval measurement.

## Separation from Retry Logic

Rate limiting controls normal request frequency. Retry delays handle temporary failures. These are separate responsibilities.

See [Retry Strategy →](./Retry-Strategy.md).

## Testing

Timing is mocked in unit tests so the suite does not actually wait. Tests verify the first request, subsequent intervals, and remaining wait time. Separate tests run real threads against a shared limiter: clients that share one never exceed its rate (while clients with their own limiters do not limit each other), slow requests overlap, the container hands every client the same limiter, and concurrent API requests share the limit while the event loop stays responsive.

See [Testing →](./Testing.md).
