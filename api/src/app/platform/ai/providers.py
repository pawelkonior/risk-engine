"""Small async model adapters without SDK-owned clients or tracing hooks."""

from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.modules.ai.contracts import Embedding

FiniteNumber = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class _ProviderResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class _Message(_ProviderResponse):
    role: Literal["assistant"]
    content: str = Field(max_length=16_000)


class _OllamaChatResponse(_ProviderResponse):
    message: _Message
    done: Literal[True]


class _EmbeddingResponse(_ProviderResponse):
    embeddings: list[list[FiniteNumber]] = Field(min_length=1, max_length=64)


class _Choice(_ProviderResponse):
    message: _Message


class _ChatCompletionResponse(_ProviderResponse):
    choices: list[_Choice] = Field(min_length=1, max_length=1)


class HTTPModelProvider:
    """Use an externally owned HTTP client and apply credentials per request."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        ollama_base_url: str,
        chat_provider: Literal["ollama", "openai_compatible"],
        chat_model: str,
        chat_base_url: str | None,
        chat_api_key: SecretStr | None,
        embedding_provider: Literal["ollama", "qdrant_cloud"],
        embedding_model: str,
        embedding_dimensions: int,
    ) -> None:
        if embedding_dimensions < 1:
            raise ValueError("embedding dimensions must be positive")
        if chat_provider == "openai_compatible" and (
            not chat_base_url or chat_api_key is None or not chat_api_key.get_secret_value()
        ):
            raise ValueError("the remote chat provider requires a base URL and API key")
        self._client = client
        self._ollama_base_url = ollama_base_url.rstrip("/")
        self._chat_provider = chat_provider
        self._chat_model = chat_model
        self._chat_base_url = chat_base_url.rstrip("/") if chat_base_url else ""
        self._chat_api_key = chat_api_key
        self._embedding_provider = embedding_provider
        self._embedding_model = embedding_model
        self._embedding_dimensions = embedding_dimensions

    async def embed(self, texts: list[str]) -> list[Embedding]:
        """Embed locally, or defer text inference to the Qdrant Cloud endpoint."""
        if not texts:
            return []
        if len(texts) > 64 or any(not text.strip() for text in texts):
            raise ValueError("embedding input requires at most 64 non-blank texts")
        if self._embedding_provider == "qdrant_cloud":
            return [{"text": text, "model": self._embedding_model} for text in texts]

        response = await self._client.post(
            f"{self._ollama_base_url}/api/embed",
            json={"model": self._embedding_model, "input": texts, "truncate": False},
        )
        response.raise_for_status()
        payload = _EmbeddingResponse.model_validate_json(response.content)
        if len(payload.embeddings) != len(texts):
            raise ValueError("the embedding provider returned an unexpected batch size")
        if any(len(vector) != self._embedding_dimensions for vector in payload.embeddings):
            raise ValueError("the embedding provider returned an unexpected vector size")
        return [list(vector) for vector in payload.embeddings]

    async def generate(self, system: str, question: str) -> str:
        """Generate a bounded non-streamed answer from Ollama or a compatible API."""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": question}]
        if self._chat_provider == "ollama":
            body: dict[str, object] = {
                "model": self._chat_model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0, "num_predict": 256},
            }
            if self._chat_model.startswith("qwen3"):
                body["think"] = False
            response = await self._client.post(f"{self._ollama_base_url}/api/chat", json=body)
            response.raise_for_status()
            answer = _OllamaChatResponse.model_validate_json(response.content).message.content
        else:
            response = await self._client.post(
                f"{self._chat_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key()}"},
                json={
                    "model": self._chat_model,
                    "messages": messages,
                    "stream": False,
                    "temperature": 0,
                    "max_tokens": 256,
                },
            )
            response.raise_for_status()
            answer = (
                _ChatCompletionResponse.model_validate_json(response.content)
                .choices[0]
                .message.content
            )
        if not answer.strip():
            raise ValueError("the chat provider returned an empty answer")
        return answer.strip()

    def _api_key(self) -> str:
        # Construction rejects absent credentials; this guard keeps the invariant explicit.
        if self._chat_api_key is None:
            raise ValueError("the remote chat provider requires an API key")
        return self._chat_api_key.get_secret_value()
