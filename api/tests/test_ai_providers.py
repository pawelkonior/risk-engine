import json
from typing import Literal

import httpx
import pytest
from pydantic import SecretStr

from app.platform.ai.providers import HTTPModelProvider

_SECRET = "MODEL_SECRET_MUST_NOT_APPEAR"


def model_provider(
    client: httpx.AsyncClient,
    *,
    chat_provider: Literal["ollama", "openai_compatible"] = "ollama",
    embedding_provider: Literal["ollama", "qdrant_cloud"] = "ollama",
    chat_model: str = "qwen3:0.6b",
) -> HTTPModelProvider:
    return HTTPModelProvider(
        client,
        ollama_base_url="http://ollama.test/",
        chat_provider=chat_provider,
        chat_model=chat_model,
        chat_base_url="https://chat.test/account/ai/v1/",
        chat_api_key=SecretStr(_SECRET),
        embedding_provider=embedding_provider,
        embedding_model="embedding-model",
        embedding_dimensions=2,
    )


async def test_ollama_embeddings_batch_and_owned_client_lifecycle() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2], [0.3, 0.4]], "model": "m"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await model_provider(client).embed(["First", "Second"])
        assert result == [[0.1, 0.2], [0.3, 0.4]]
        assert not client.is_closed
    assert client.is_closed
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "http://ollama.test/api/embed"
    assert request.method == "POST"
    assert "authorization" not in request.headers
    assert json.loads(request.content) == {
        "model": "embedding-model",
        "input": ["First", "Second"],
        "truncate": False,
    }


async def test_cloud_embeddings_defer_inference_without_http_or_local_models() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await model_provider(client, embedding_provider="qdrant_cloud").embed(
            ["First", "Second"]
        )
        assert result == [
            {"text": "First", "model": "embedding-model"},
            {"text": "Second", "model": "embedding-model"},
        ]
        assert await model_provider(client).embed([]) == []
    assert not requests


@pytest.mark.parametrize("texts", [[" "], ["valid", ""], ["text"] * 65])
async def test_embedding_input_is_bounded_before_network_access(texts: list[str]) -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="at most 64 non-blank"):
            await model_provider(client).embed(texts)


@pytest.mark.parametrize(
    "body",
    [
        b'{"embeddings":[[0.1,0.2],[0.3,0.4]]}',
        b'{"embeddings":[[0.1]]}',
        b'{"embeddings":[[NaN,0.2]]}',
        b'{"embeddings":[[Infinity,0.2]]}',
        b'{"embeddings":[[true,0.2]]}',
        b'{"embeddings":[["MODEL_SECRET_MUST_NOT_APPEAR",0.2]]}',
        b'{"embeddings":[]}',
        b'{"private":"MODEL_SECRET_MUST_NOT_APPEAR"}',
        b"MODEL_SECRET_MUST_NOT_APPEAR",
    ],
)
async def test_invalid_embedding_responses_are_rejected_without_echoing_values(body: bytes) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
    ) as client:
        with pytest.raises(ValueError) as error:
            await model_provider(client).embed(["Input"])
    assert _SECRET not in str(error.value)


async def test_ollama_chat_has_explicit_non_streamed_generation_bounds() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "  Answer [S1].  "},
                "done": True,
                "eval_count": 5,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        assert await model_provider(client).generate("Use sources.", "Question?") == "Answer [S1]."
    assert str(requests[0].url) == "http://ollama.test/api/chat"
    assert json.loads(requests[0].content) == {
        "model": "qwen3:0.6b",
        "messages": [
            {"role": "system", "content": "Use sources."},
            {"role": "user", "content": "Question?"},
        ],
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_predict": 256},
    }
    assert "authorization" not in requests[0].headers


async def test_non_thinking_ollama_models_do_not_receive_unsupported_think_option() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200, json={"message": {"role": "assistant", "content": "Answer"}, "done": True}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = model_provider(client, chat_model="gemma3:1b")
        assert await provider.generate("System", "Q") == "Answer"
    assert "think" not in json.loads(requests[0].content)


async def test_compatible_chat_credentials_are_scoped_to_chat_request() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("chat/completions"):
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"role": "assistant", "content": " Answer "}}],
                    "usage": {"total_tokens": 3},
                },
            )
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = model_provider(client, chat_provider="openai_compatible")
        assert await provider.generate("System", "Question") == "Answer"
        assert await provider.embed(["Input"]) == [[0.1, 0.2]]
        assert "authorization" not in client.headers
    assert str(requests[0].url) == "https://chat.test/account/ai/v1/chat/completions"
    assert requests[0].headers["authorization"] == f"Bearer {_SECRET}"
    assert "authorization" not in requests[1].headers
    assert json.loads(requests[0].content) == {
        "model": "qwen3:0.6b",
        "messages": [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Question"},
        ],
        "stream": False,
        "temperature": 0,
        "max_tokens": 256,
    }


@pytest.mark.parametrize(
    ("kind", "body"),
    [
        ("ollama", b'{"message":{"role":"assistant","content":" "},"done":true}'),
        ("ollama", b'{"message":{"role":"assistant","content":"x"},"done":false}'),
        ("ollama", b'{"message":{"role":"assistant","content":"x"}}'),
        (
            "ollama",
            b'{"message":{"role":"user","content":"MODEL_SECRET_MUST_NOT_APPEAR"},"done":true}',
        ),
        ("openai_compatible", b'{"choices":[]}'),
        ("openai_compatible", b'{"choices":[{"message":{"role":"assistant","content":" "}}]}'),
        ("openai_compatible", b'{"choices":[{"message":{"role":"assistant","content":null}}]}'),
        ("openai_compatible", b'{"private":"MODEL_SECRET_MUST_NOT_APPEAR"}'),
    ],
)
async def test_invalid_chat_responses_are_rejected_without_echoing_values(
    kind: Literal["ollama", "openai_compatible"], body: bytes
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
    ) as client:
        with pytest.raises(ValueError) as error:
            await model_provider(client, chat_provider=kind).generate("System", "Question")
    assert _SECRET not in str(error.value)


@pytest.mark.parametrize("kind", ["ollama", "openai_compatible"])
async def test_failed_chat_http_status_is_propagated_without_response_body(
    kind: Literal["ollama", "openai_compatible"],
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text=_SECRET))
    ) as client:
        with pytest.raises(httpx.HTTPStatusError) as error:
            await model_provider(client, chat_provider=kind).generate("System", "Question")
    assert _SECRET not in str(error.value)


async def test_embedding_failure_and_timeouts_propagate_without_internal_retries() -> None:
    requests: list[httpx.Request] = []

    def timeout(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ReadTimeout("Timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(httpx.TimeoutException):
            await model_provider(client).embed(["Input"])
        assert len(requests) == 1
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text=_SECRET))
    ) as client:
        with pytest.raises(httpx.HTTPStatusError) as error:
            await model_provider(client).embed(["Input"])
    assert _SECRET not in str(error.value)


@pytest.mark.parametrize(
    ("base", "key"),
    [(None, SecretStr(_SECRET)), ("https://chat.test", None), ("https://chat.test", SecretStr(""))],
)
async def test_remote_chat_requires_explicit_credentials(
    base: str | None, key: SecretStr | None
) -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="base URL and API key"):
            HTTPModelProvider(
                client,
                ollama_base_url="http://ollama.test",
                chat_provider="openai_compatible",
                chat_model="model",
                chat_base_url=base,
                chat_api_key=key,
                embedding_provider="qdrant_cloud",
                embedding_model="model",
                embedding_dimensions=2,
            )


async def test_embedding_dimensions_must_be_positive() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="dimensions must be positive"):
            HTTPModelProvider(
                client,
                ollama_base_url="http://ollama.test",
                chat_provider="ollama",
                chat_model="model",
                chat_base_url=None,
                chat_api_key=None,
                embedding_provider="ollama",
                embedding_model="model",
                embedding_dimensions=0,
            )
