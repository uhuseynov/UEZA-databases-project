from urllib.parse import urlsplit

import httpx


class LLMError(RuntimeError):
    """The language model could not be reached or returned something unusable.

    The message is for server-side logs: it names the endpoint (without credentials or query
    string) and may quote the start of the upstream reply. It must never be sent to API
    clients; the API answers with a fixed message instead.
    """


def _without_credentials(url: str) -> str:
    """``scheme://host:port/path``: no user name, password or query string."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return "<invalid LLM URL>"
    return f"{parts.scheme}://{host}{port}{parts.path}"


class ChatLLM:
    """Client for any OpenAI-compatible ``/chat/completions`` endpoint.

    That covers the OpenAI API as well as local servers such as Ollama
    (``http://localhost:11434/v1``), so the project can run without a paid key.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.2,
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self._client = client

    def _clean(self, text: str) -> str:
        """Remove the API key and the raw (possibly credentialed) URLs from text for logs."""
        for raw in (f"{self.base_url}/chat/completions", self.base_url):
            text = text.replace(raw, _without_credentials(raw))
        if self.api_key:
            text = text.replace(self.api_key, "***")
        return text

    async def complete(self, messages: list[dict[str, str]]) -> str:
        """Send the chat messages and return the model's reply text."""
        url = f"{self.base_url}/chat/completions"
        endpoint = _without_credentials(url)  # for error messages and logs only
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            if self._client is not None:
                response = await self._client.post(
                    url, json=payload, headers=headers, timeout=self.timeout
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            detail = self._clean(f"{type(exc).__name__}: {exc}")
            raise LLMError(f"LLM request to {endpoint} failed: {detail}") from exc

        if response.status_code != 200:
            raise LLMError(
                f"LLM at {endpoint} returned HTTP {response.status_code}: "
                f"{self._clean(response.text[:200])}"
            )

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError(f"LLM response from {endpoint} did not have the expected format") from exc

        if not isinstance(content, str):
            raise LLMError(f"LLM response from {endpoint} is not text")
        return content.strip()
