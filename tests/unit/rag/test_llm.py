import json

import httpx
import pytest

from src.rag.llm import ChatLLM, LLMError

pytestmark = pytest.mark.anyio

MESSAGES = [{"role": "user", "content": "hi"}]


def make_llm(handler, api_key: str = "secret") -> ChatLLM:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ChatLLM(
        base_url="http://llm.test/v1/",
        api_key=api_key,
        model="test-model",
        temperature=0.1,
        client=client,
    )


def reply(content) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


async def test_sends_an_openai_compatible_request():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return reply("  An answer [1]  ")

    answer = await make_llm(handler).complete(MESSAGES)

    assert answer == "An answer [1]"
    request = seen[0]
    assert str(request.url) == "http://llm.test/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer secret"
    assert json.loads(request.content) == {
        "model": "test-model",
        "messages": MESSAGES,
        "temperature": 0.1,
    }


async def test_no_authorization_header_without_a_key():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return reply("ok")

    await make_llm(handler, api_key="").complete(MESSAGES)

    assert "Authorization" not in seen[0].headers


async def test_http_error_status_raises_llm_error():
    llm = make_llm(lambda request: httpx.Response(401, text="invalid api key"))

    with pytest.raises(LLMError, match="401"):
        await llm.complete(MESSAGES)


async def test_unexpected_body_raises_llm_error():
    llm = make_llm(lambda request: httpx.Response(200, json={"unexpected": True}))

    with pytest.raises(LLMError, match="format"):
        await llm.complete(MESSAGES)


async def test_non_text_content_raises_llm_error():
    llm = make_llm(lambda request: reply(None))

    with pytest.raises(LLMError, match="not text"):
        await llm.complete(MESSAGES)


async def test_connection_problem_raises_llm_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(LLMError, match="failed"):
        await make_llm(handler).complete(MESSAGES)
