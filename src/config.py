"""Central application configuration."""

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ---------------------------------------------------------
    # Application
    # ---------------------------------------------------------

    app_env: Literal["development", "production"] = "development"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    app_port: int = Field(default=8000, ge=1, le=65535)
    app_host: str = "0.0.0.0"

    # ---------------------------------------------------------
    # MariaDB
    # ---------------------------------------------------------

    mariadb_host: str = "db"
    mariadb_port: int = Field(default=3306, ge=1, le=65535)

    mariadb_user: str = "ueza"
    mariadb_password: str = "ueza_password"
    mariadb_database: str = "ueza_db"

    mariadb_pool_recycle: int = Field(default=3600, ge=60)
    mariadb_pool_pre_ping: bool = True

    # ---------------------------------------------------------
    # Article cache
    # ---------------------------------------------------------

    cache_dir: str = ".cache/articles"
    cache_ttl_seconds: int = Field(default=86400, ge=0)

    # ---------------------------------------------------------
    # MediaWiki API
    # ---------------------------------------------------------

    mediawiki_user_agent: str = (
        "UEZA-Databases-Project/0.1 "
        "(https://github.com/uhuseynov/UEZA-databases-project; "
        "mailto:info@constructor.university)"
    )

    mediawiki_requests_per_second: float = Field(default=2.0, gt=0)

    mediawiki_max_retries: int = Field(default=3, ge=0)
    mediawiki_batch_size: int = Field(default=20, ge=1)
    mediawiki_timeout: float = Field(default=10.0, gt=0)
    mediawiki_maxlag: int = Field(default=5, ge=0)

    # ---------------------------------------------------------
    # Ingestion
    # ---------------------------------------------------------

    articles_csv_path: str = "data/articles.csv"

    chunk_config: Literal["A", "B", "C"] = "A"

    # A: 256 tokens, 32 overlap
    # B: 512 tokens, 64 overlap
    # C: Paragraph-based, max 512 tokens, no overlap

    ingestion_snapshot: bool = True

    # ---------------------------------------------------------
    # Embeddings
    # ---------------------------------------------------------

    embedding_model_name: str = "BAAI/bge-base-en-v1.5"

    embedding_dimension: int = Field(default=768, ge=1)

    embedding_query_prefix: str = "Represent this sentence for searching relevant passages: "

    embedding_passage_prefix: str = ""

    vector_search_top_k: int = Field(default=5, ge=1)

    # ---------------------------------------------------------
    # LLM / RAG
    # ---------------------------------------------------------

    llm_api_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)

    llm_timeout_seconds: float = Field(default=60.0, gt=0)

    # ---------------------------------------------------------
    # RAG / Evaluation
    # ---------------------------------------------------------

    rag_max_distance: float = Field(default=0.42, gt=0.0, le=2.0)

    ground_truth_path: str = "data/ground_truth.csv"
    eval_results_dir: str = "eval/results"

    # ---------------------------------------------------------
    # Validation
    # ---------------------------------------------------------

    @model_validator(mode="after")
    def validate_settings(self):
        if self.chunk_config not in {"A", "B", "C"}:
            raise ValueError("Invalid chunk configuration")

        return self

    # ---------------------------------------------------------
    # Database URLs
    # ---------------------------------------------------------

    @property
    def database_url(self) -> str:
        """Async SQLAlchemy connection URL."""

        from sqlalchemy.engine import URL

        return URL.create(
            drivername="mysql+aiomysql",
            username=self.mariadb_user,
            password=self.mariadb_password,
            host=self.mariadb_host,
            port=self.mariadb_port,
            database=self.mariadb_database,
            query={"charset": "utf8mb4"},
        ).render_as_string(hide_password=False)

    @property
    def sync_database_url(self) -> str:
        """Synchronous SQLAlchemy connection URL."""

        from sqlalchemy.engine import URL

        return URL.create(
            drivername="mysql+pymysql",
            username=self.mariadb_user,
            password=self.mariadb_password,
            host=self.mariadb_host,
            port=self.mariadb_port,
            database=self.mariadb_database,
            query={"charset": "utf8mb4"},
        ).render_as_string(hide_password=False)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
