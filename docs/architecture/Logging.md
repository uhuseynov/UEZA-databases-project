# Logging

[← Architecture](./Home.md) | [Documentation Home](../Home.md)

Application logging is configured by `AppLogger` in `src/logger.py`.

## Development

Outside production, logs use a human-readable format containing the timestamp, level, logger name, and message.

## Production

When `APP_ENV=production`, logging uses `python-json-logger` and emits structured JSON logs.

## Log Level

`LOG_LEVEL` supports DEBUG, INFO, WARNING, ERROR, and CRITICAL.

## Shared Logger

`AppLogger` is provided as a singleton by the dependency injection container. Components request module-specific loggers through:

```python
logger.get_logger(__name__)
```

The setup process clears existing root handlers before adding the configured handler, avoiding duplicate output when initialization occurs more than once.
