from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration settings."""

    # Application & Logging
    app_env: str = Field(
        default="development",
        pattern=r"^(development|production)$",
    )
    log_level: str = Field(
        default="INFO",
        pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$",
    )
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_host: str = "0.0.0.0"

    # MariaDB Connection & Pool Settings
    mariadb_host: str = "mariadb"
    mariadb_port: int = Field(default=3306, ge=1, le=65535)
    mariadb_user: str = "root"
    mariadb_password: str = "ueza_password"
    mariadb_database: str = "ueza_db"
    mariadb_pool_recycle: int = Field(default=3600, ge=60)
    mariadb_pool_pre_ping: bool = True

    # Ingestion Cache Settings
    cache_dir: str = ".cache/articles"
    cache_ttl_seconds: int = Field(default=86400, ge=0)

    # MediaWiki Client Settings
    mediawiki_user_agent: str = (
        "UEZA-Databases-Project/0.1 "
        "(https://github.com/uhuseynov/UEZA-databases-project; "
        "mailto:infon@constructor.university)"
    )
    mediawiki_requests_per_second: float = Field(default=2.0, gt=0)
    mediawiki_max_retries: int = Field(default=3, ge=0)
    mediawiki_batch_size: int = Field(default=20, ge=1)
    mediawiki_timeout: float = Field(default=10.0, gt=0)
    mediawiki_maxlag: int = Field(default=5, ge=0)

    # Chunking Configuration
    chunk_size: int = Field(default=1000, ge=100)
    chunk_overlap: int = Field(default=150, ge=0)

    # Vector & Embeddings Configuration
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = Field(default=384, ge=1)
    vector_search_top_k: int = Field(default=5, ge=1)

    # LLM / RAG Configuration
    llm_api_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        """Return the asynchronous SQLAlchemy database URL."""
        return (
            f"mysql+aiomysql://{self.mariadb_user}:"
            f"{self.mariadb_password}@"
            f"{self.mariadb_host}:"
            f"{self.mariadb_port}/"
            f"{self.mariadb_database}"
            "?charset=utf8mb4"
        )

    @property
    def sync_database_url(self) -> str:
        """Return the synchronous SQLAlchemy database URL."""
        return (
            f"mysql+pymysql://{self.mariadb_user}:"
            f"{self.mariadb_password}@"
            f"{self.mariadb_host}:"
            f"{self.mariadb_port}/"
            f"{self.mariadb_database}"
            "?charset=utf8mb4"
        )


settings = Settings()
