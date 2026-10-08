# Configuration

[← Architecture](./Home.md) | [Documentation Home](../Home.md)

Application configuration is defined in `src/config.py` using Pydantic Settings.

## Environment Loading

Settings are loaded from environment variables and, during local development, from `.env`.

```python
model_config = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
)
```

Environment variables can therefore override defaults without changing source code.

## Application Settings

Current application-level settings include `APP_ENV`, `LOG_LEVEL`, `APP_HOST`, and `APP_PORT`.

`APP_ENV` is restricted to `development` or `production`. Logging behavior changes according to this environment.

## MariaDB Settings

Database configuration includes the host, port, user, password, database name, pool recycle interval, and pool pre-ping behavior.

### Asynchronous URL

`database_url` uses:

```text
mysql+aiomysql://
```

This URL is used by the running application through SQLAlchemy's async engine.

### Synchronous URL

`sync_database_url` uses:

```text
mysql+pymysql://
```

This URL is intended for synchronous tooling such as Alembic migrations.

## Ingestion Settings

Configuration currently includes settings for the article cache and MediaWiki client, including request rate, timeout, retries, batch size, `maxlag`, and `MEDIAWIKI_USER_AGENT`. The default User-Agent identifies this project with its repository URL and a contact address, as required for reliable Wikimedia API access. Override it through environment configuration when deploying under a different application identity.

The configuration also contains planned chunking, embedding, vector-search, and LLM/RAG settings. Their presence does not mean those pipeline stages are implemented yet.

## Docker and Local Development

The default MariaDB host is `mariadb`, suitable when the database service uses that hostname inside a Docker Compose network.

When the Python application runs directly on the host machine while MariaDB is exposed locally, override it in `.env`:

```dotenv
MARIADB_HOST=localhost
```

Secrets such as database passwords and API keys should be supplied through environment configuration and should not be committed in a real `.env` file.
