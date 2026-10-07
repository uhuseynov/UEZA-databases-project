# Database Connection and Sessions

[← Database](./Home.md) | [Documentation Home](../Home.md)

`src/database/connection.py` contains the `Database` class, which manages the asynchronous SQLAlchemy engine and session factory.

## Engine

The engine is created with `create_async_engine()` using the configured `mysql+aiomysql` URL.

Current pool behavior includes configurable `pool_pre_ping`, configurable `pool_recycle`, and SQL echo output when `LOG_LEVEL=DEBUG`.

## Lifecycle

```text
FastAPI startup
      ↓
Database.connect()
      ↓
AsyncEngine + session factory

FastAPI shutdown
      ↓
Database.disconnect()
      ↓
engine.dispose()
```

The connection-pool lifetime therefore follows the application lifetime.

## Sessions

`get_session()` is an async context manager.

Successful operations are committed automatically:

```text
open session
    ↓
yield session
    ↓
COMMIT
    ↓
close session
```

If an exception escapes the context:

```text
open session
    ↓
operation fails
    ↓
ROLLBACK
    ↓
exception re-raised
    ↓
close session
```

This provides a transaction boundary suitable for operations that must update several related records atomically.

## Session Configuration

Sessions currently use `AsyncSession`, `expire_on_commit=False`, and `autoflush=False`.

## Connection Guard

Calling `get_session()` before `connect()` raises `RuntimeError`, preventing use of an uninitialized database manager.
