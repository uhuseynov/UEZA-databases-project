import httpx

from src.ingestion.cache import ArticleCache


def test_client_uses_cached_article(tmp_path, client_factory, article_response):
    cache = ArticleCache(cache_dir=str(tmp_path), ttl_seconds=3600)
    network_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal network_requests
        network_requests += 1
        return httpx.Response(200, json=article_response(title="Python"))

    client = client_factory(handler, cache=cache)

    # 1. Request - Cache miss -> Should make a network request
    article1 = client.get_article("Python")
    assert network_requests == 1
    assert article1.title == "Python"

    # 2. Request - Cache hit -> Should NOT make a network request
    article2 = client.get_article("Python")
    assert network_requests == 1
    assert article2.title == "Python"
