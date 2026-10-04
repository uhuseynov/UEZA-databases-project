from dependency_injector import containers, providers

from config import settings
from database import Database
from ingestion.cache import ArticleCache
from ingestion.mediawiki import MediaWikiClient
from logger import AppLogger


class Container(containers.DeclarativeContainer):
    """Dependency injection container for application components."""

    config = providers.Object(settings)
    app_logger = providers.Singleton(AppLogger, settings=config)
    database = providers.Singleton(Database, settings=config, logger=app_logger)

    article_cache = providers.Singleton(
        ArticleCache,
        cache_dir=config.provided.cache_dir,
        ttl_seconds=config.provided.cache_ttl_seconds,
    )

    mediawiki_client = providers.Factory(
        MediaWikiClient,
        user_agent=config.provided.mediawiki_user_agent,
        requests_per_second=config.provided.mediawiki_requests_per_second,
        timeout=config.provided.mediawiki_timeout,
        max_retries=config.provided.mediawiki_max_retries,
        maxlag=config.provided.mediawiki_maxlag,
        batch_size=config.provided.mediawiki_batch_size,
        logger=app_logger,
        cache=article_cache,
    )
