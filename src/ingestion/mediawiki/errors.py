class MediaWikiError(Exception):
    """Base exception for all MediaWiki client errors."""


class MediaWikiRequestError(MediaWikiError):
    """Network or HTTP request failed."""


class MediaWikiAPIError(MediaWikiError):
    """MediaWiki returned an API-level error."""


class MediaWikiPageNotFoundError(MediaWikiError):
    """Requested Wikipedia page does not exist."""


class MediaWikiRateLimitError(MediaWikiError):
    """MediaWiki rate limit remained exceeded after retries."""


class MediaWikiInvalidResponseError(MediaWikiError):
    """MediaWiki returned malformed or unexpected data."""
