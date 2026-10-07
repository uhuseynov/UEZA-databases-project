# MediaWiki Retry Strategy

[← MediaWiki](./Home.md) | [Documentation Home](../../Home.md)

Requests to an external API can fail temporarily. The client retries selected transient failures up to a configured maximum.

## Retryable Conditions

- Network request errors
- HTTP 429
- HTTP 502
- HTTP 503
- HTTP 504
- MediaWiki `maxlag`

## HTTP 429 and Retry-After

HTTP 429 is treated as retryable. When available, `Retry-After` is used to determine the delay. It may be expressed as seconds or an HTTP date.

## Transient Server Errors

HTTP 502, 503, and 504 are treated as temporary infrastructure or upstream failures and are retried.

## MediaWiki maxlag

MediaWiki can return a `maxlag` API error when backend replication or server load is too high. This is treated as temporary and retried.

## Network Errors

Transport-level request failures are retried until the configured retry limit is exhausted.

## Backoff

When no explicit retry delay is available, retries use backoff rather than immediately repeating the failed request.

## Retry Limit

Retries are bounded. Once the configured retry count is exhausted, the appropriate project-level exception is raised.

## Non-Retryable Failures

Failures not classified as temporary are not blindly retried, including invalid responses and ordinary non-`maxlag` API errors.

## Relationship with Rate Limiting

| Mechanism | Purpose |
|---|---|
| Rate limiting | Controls normal request frequency |
| Retry delay | Handles temporary failures |

See [Rate Limiting →](./Rate-Limiting.md).

## Testing

Retry tests simulate 429, 502, 503, 504, retry exhaustion, `maxlag`, persistent `maxlag`, and non-retryable failures. Actual retry sleeping is disabled during unit tests.

See [Testing →](./Testing.md).
