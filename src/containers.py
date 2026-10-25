"""Dependency injection container for the application."""

from dependency_injector import containers, providers

from src.config import settings
from src.database import Database
from src.database.repositories.articles import ArticleRepository
from src.ingestion.cache import ArticleCache
from src.ingestion.mediawiki import MediaWikiClient
from src.ingestion.pipeline import IngestionPipeline
from src.logger import AppLogger
from src.rag.embedder import Embedder
from src.rag.llm import ChatLLM
from src.rag.retriever import VectorRetriever
from src.rag.service import RAGService


class Container(containers.DeclarativeContainer):
    """Provide shared application dependencies."""

    # ---------------------------------------------------------
    # Configuration and logging
    # ---------------------------------------------------------

    config = providers.Object(settings)

    app_logger = providers.Singleton(
        AppLogger,
        settings=config,
    )

    # ---------------------------------------------------------
    # Database
    # ---------------------------------------------------------

    database = providers.Singleton(
        Database,
        settings=config,
        logger=app_logger,
    )

    article_repository = providers.Factory(
        ArticleRepository,
        database=database,
    )

    # ---------------------------------------------------------
    # MediaWiki cache and client
    # ---------------------------------------------------------

    article_cache = providers.Singleton(
        ArticleCache,
        cache_dir=config.provided.cache_dir,
        ttl_seconds=config.provided.cache_ttl_seconds,
    )

    mediawiki_client = providers.Factory(
        MediaWikiClient,
        user_agent=config.provided.mediawiki_user_agent,
        requests_per_second=(config.provided.mediawiki_requests_per_second),
        timeout=config.provided.mediawiki_timeout,
        max_retries=config.provided.mediawiki_max_retries,
        maxlag=config.provided.mediawiki_maxlag,
        batch_size=config.provided.mediawiki_batch_size,
        logger=app_logger,
        cache=article_cache,
    )

    # ---------------------------------------------------------
    # Embedding model
    # ---------------------------------------------------------

    embedder = providers.ThreadSafeSingleton(
        Embedder,
        model_name=config.provided.embedding_model_name,
        dimension=config.provided.embedding_dimension,
        query_prefix=config.provided.embedding_query_prefix,
        passage_prefix=config.provided.embedding_passage_prefix,
    )

    # ---------------------------------------------------------
    # Ingestion
    # ---------------------------------------------------------

    ingestion_pipeline = providers.Factory(
        IngestionPipeline,
        client=mediawiki_client,
        embedder=embedder,
        repository=article_repository,
    )

    # ---------------------------------------------------------
    # Vector retrieval
    # ---------------------------------------------------------

    retriever = providers.Singleton(
        VectorRetriever,
        database=database,
    )

    # ---------------------------------------------------------
    # LLM
    # ---------------------------------------------------------

    llm = providers.Singleton(
        ChatLLM,
        base_url=config.provided.llm_api_base_url,
        api_key=config.provided.llm_api_key,
        model=config.provided.llm_model,
        temperature=config.provided.llm_temperature,
        timeout=config.provided.llm_timeout_seconds,
    )

    # ---------------------------------------------------------
    # RAG service
    # ---------------------------------------------------------

    rag_service = providers.Singleton(
        RAGService,
        embedder=embedder,
        retriever=retriever,
        llm=llm,
        top_k=config.provided.vector_search_top_k,
        max_distance=config.provided.rag_max_distance,
    )
