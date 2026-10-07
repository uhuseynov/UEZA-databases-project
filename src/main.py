from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from config import settings
from containers import Container
from database import Database
from ingestion.mediawiki import MediaWikiClient, MediaWikiError, WikiArticle


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
    container.wire(modules=[__name__])

    app = FastAPI(
        title="UEZA Databases Project",
        description="Native vector search and RAG evaluation using MariaDB",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.container = container

    @app.get("/health")
    async def health_check():
        return {"status": "ok"}

    @app.get("/articles/{title}")
    async def get_wiki_article(
        title: str,
        request: Request,
    ) -> WikiArticle:
        try:
            client: MediaWikiClient = request.app.state.container.mediawiki_client()
            return client.get_article(title)
        except MediaWikiError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=settings.app_host, port=settings.app_port, reload=True)
