import httpx


class LLMError(RuntimeError):
    """The language model could not be reached or returned something unusable."""


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

    async def complete(self, messages: list[dict[str, str]]) -> str:
        """Send the chat messages and return the model's reply text."""
        url = f"{self.base_url}/chat/completions"
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
            raise LLMError(f"LLM request to {url} failed: {exc}") from exc

        if response.status_code != 200:
            raise LLMError(
                f"LLM returned HTTP {response.status_code}: {response.text[:200]}"
            )

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError("LLM response did not have the expected format") from exc

        if not isinstance(content, str):
            raise LLMError("LLM response content is not text")
        return content.strip()
