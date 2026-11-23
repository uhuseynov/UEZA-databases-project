from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.routes import router as rag_router
from src.config import settings
from src.containers import Container
from src.database import Database


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Manages application lifecycle: connects and disconnects database."""
    container: Container = app.state.container
    logger = container.app_logger().get_logger(__name__)
    database: Database = container.database()

    logger.info("Application starting up...")
    await database.connect()

    yield

    logger.info("Application shutting down...")
    await database.disconnect()


def create_app() -> FastAPI:
    """Application factory with dependency injection setup."""
    container = Container()
    container.app_logger().setup()

    app = FastAPI(
        title="UEZA Databases Project",
        description="Native vector search and RAG evaluation using MariaDB",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.container = container
    app.include_router(rag_router)

    @app.get("/health")
    async def health_check():
        return {"status": "ok"}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.main:app", host=settings.app_host, port=settings.app_port, reload=True)
