import contextlib
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import Settings
from logger import AppLogger


class Database:
    """Manages the asynchronous MariaDB connection pool and sessions."""

    def __init__(self, settings: Settings, logger: AppLogger) -> None:
        self.db_url = settings.database_url
        self.echo = settings.log_level == "DEBUG"
        self.pool_recycle = settings.mariadb_pool_recycle
        self.pool_pre_ping = settings.mariadb_pool_pre_ping
        self.logger = logger.get_logger(__name__)
        self.engine: AsyncEngine | None = None
        self.session_factory: async_sessionmaker[AsyncSession] | None = None

    async def connect(self) -> None:
        """Initialize the database engine and session factory."""
        if self.engine is not None:
            self.logger.info("Database engine already initialized.")
            return

        self.logger.info("Initializing MariaDB connection pool...")
        self.engine = create_async_engine(
            self.db_url,
            echo=self.echo,
            pool_pre_ping=self.pool_pre_ping,
            pool_recycle=self.pool_recycle,
        )
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        self.logger.info("MariaDB connection pool initialized.")

    async def disconnect(self) -> None:
        """Dispose of the database engine and connection pool."""
        if self.engine is None:
            return

        self.logger.info("Closing MariaDB connections...")
        await self.engine.dispose()
        self.engine = None
        self.session_factory = None
        self.logger.info("MariaDB connections closed.")

    @contextlib.asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession]:
        """Provide a transactional database session."""
        if self.session_factory is None:
            raise RuntimeError("Database is not connected. Call connect() first.")

        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                self.logger.exception("Transaction failed. Rolling back session.")
                await session.rollback()
                raise
