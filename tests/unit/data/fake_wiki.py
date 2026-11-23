"""A small fake English Wikipedia for the article-list script: categories, pages and redirects."""

import json

import httpx


class FakeWiki:
    """Answers the three queries of ``data/build_article_list.py`` the way MediaWiki does."""

    def __init__(self) -> None:
        self.categories: dict[str, dict[str, list[str]]] = {}
        self.pages: dict[str, tuple[int, int, str]] = {}
        self.redirects: dict[str, str] = {}
        self.requests: list[httpx.Request] = []

    def category(self, title: str, articles: list[str], subcategories: list[str] | None = None):
        self.categories[title] = {"articles": articles, "subcategories": subcategories or []}

    def page(self, title: str, pageid: int, length: int, timestamp: str = "2026-09-01T10:00:00Z"):
        self.pages[title] = (pageid, length, timestamp)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        params = request.url.params

        if params.get("list") == "categorymembers":
            category = self.categories.get(params["cmtitle"], {"articles": [], "subcategories": []})
            members = [{"ns": 0, "title": t} for t in category["articles"]] + [
                {"ns": 14, "title": t} for t in category["subcategories"]
            ]
            return httpx.Response(200, json={"query": {"categorymembers": members}})

        pages = []
        seen: set[str] = set()
        for title in params["titles"].split("|"):
            if "redirects" in params:
                title = self.redirects.get(title, title)
            if title in seen:
                continue
            seen.add(title)
            if title in self.pages:
                pageid, length, timestamp = self.pages[title]
                pages.append(
                    {
                        "pageid": pageid,
                        "title": title,
                        "length": length,
                        "revisions": [{"timestamp": timestamp}],
                    }
                )
            else:
                pages.append({"title": title, "missing": True})
        return httpx.Response(200, json={"query": {"pages": pages}})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def serialized(response: httpx.Response) -> str:
    return json.dumps(response.json(), sort_keys=True)
