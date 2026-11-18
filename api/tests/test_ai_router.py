import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import Mock, create_autospec
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from pytest import LogCaptureFixture, MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.errors import NotFoundError
from app.http.dependencies import database_session
from app.main import create_app
from app.modules.ai import router
from app.modules.ai.contracts import KnowledgeStore, ModelProvider, VectorStore
from app.modules.ai.domain import DocumentInput, DocumentStatus, QueryInput, QueryResponse
from app.modules.ai.service import AiService
from app.modules.ai.workflow import NO_SOURCES_ANSWER
from app.platform.ai import observability
from app.platform.ai.runtime import AIResources

_SECRET = "AI_ROUTER_SECRET_MUST_NOT_APPEAR"


def application(settings: Settings, service: Mock | None = None) -> FastAPI:
    app = create_app(settings)
    if service is not None:
        app.dependency_overrides[router.service] = lambda: service
    return app


async def test_status_returns_identity_without_secrets_or_external_io(
    monkeypatch: MonkeyPatch, test_settings: Settings
) -> None:
    resources = Mock(side_effect=AssertionError("status must not construct resources"))
    monkeypatch.setattr(router, "ai_resources", resources)
    app = application(test_settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/ai/status")
    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "chat_provider": "ollama",
        "chat_model": "qwen3:0.6b",
        "embedding_provider": "ollama",
        "embedding_model": "embeddinggemma",
        "collection": "app_chunks_ollama_v1",
    }
    assert "password" not in response.text
    assert "api_key" not in response.text
    resources.assert_not_called()


async def test_disabled_ai_rejects_mutations_and_queries_without_external_io(
    monkeypatch: MonkeyPatch, test_settings: Settings
) -> None:
    resources = Mock(side_effect=AssertionError("disabled AI must not create resources"))
    monkeypatch.setattr(router, "ai_resources", resources)
    app = application(test_settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = [
            await client.put(
                f"/api/v1/ai/documents/{uuid4()}", json={"title": "T", "text": "Text"}
            ),
            await client.get(f"/api/v1/ai/documents/{uuid4()}"),
            await client.post("/api/v1/ai/query", json={"question": "Q"}),
        ]
    for response in responses:
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "service_unavailable"
        assert response.json()["error"]["message"] == "AI is disabled for this application"
    resources.assert_not_called()


async def test_documents_and_query_use_typed_service_contracts(test_settings: Settings) -> None:
    service = create_autospec(AiService, instance=True)
    document_id = uuid4()
    status = DocumentStatus(
        document_id=document_id,
        namespace="cards",
        status="ready",
        chunk_count=1,
        collection="test",
    )
    service.ingest.return_value = service.status.return_value = status
    service.query.return_value = QueryResponse(answer="Answer", sources=[], facts=[])
    app = application(test_settings, service)
    payload = {"namespace": "cards", "title": "Title", "text": "Text"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ingested = await client.put(f"/api/v1/ai/documents/{document_id}", json=payload)
        retrieved = await client.get(
            f"/api/v1/ai/documents/{document_id}", params={"namespace": "cards"}
        )
        queried = await client.post(
            "/api/v1/ai/query", json={"namespace": "cards", "question": "Q", "limit": 2}
        )
    assert ingested.status_code == retrieved.status_code == queried.status_code == 200
    assert ingested.json() == retrieved.json() == status.model_dump(mode="json")
    assert queried.json() == {"answer": "Answer", "sources": [], "facts": []}
    service.ingest.assert_awaited_once_with(
        document_id, DocumentInput(namespace="cards", title="Title", text="Text")
    )
    service.status.assert_awaited_once_with(document_id, "cards")
    service.query.assert_awaited_once_with(QueryInput(namespace="cards", question="Q", limit=2))


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("PUT", "/documents/not-a-uuid", {"title": "T", "text": "Text"}),
        ("PUT", f"/documents/{uuid4()}", {"title": "T", "text": " "}),
        ("PUT", f"/documents/{uuid4()}", {"title": "T", "text": "Text", "extra": _SECRET}),
        ("GET", f"/documents/{uuid4()}?namespace=invalid%2Fnamespace", None),
        ("POST", "/query", {"question": " "}),
        ("POST", "/query", {"question": "Q", "limit": 9}),
        ("POST", "/query", {"question": "Q", "unexpected": _SECRET}),
    ],
)
async def test_invalid_api_inputs_return_safe_422_before_service_calls(
    test_settings: Settings, method: str, path: str, payload: dict[str, object] | None
) -> None:
    service = create_autospec(AiService, instance=True)
    app = application(test_settings, service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, f"/api/v1/ai{path}", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert _SECRET not in response.text
    service.ingest.assert_not_awaited()
    service.status.assert_not_awaited()
    service.query.assert_not_awaited()


async def test_document_not_found_uses_public_error_envelope(test_settings: Settings) -> None:
    service = create_autospec(AiService, instance=True)
    service.status.side_effect = NotFoundError("Document was not indexed")
    app = application(test_settings, service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/ai/documents/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("operation", ["ingest", "query", "status"])
async def test_request_deadlines_cancel_work_and_return_503(operation: str) -> None:
    settings = Settings(_env_file=None, ai_request_timeout_seconds=0.001)
    service = create_autospec(AiService, instance=True)
    cancelled = asyncio.Event()

    async def wait_forever(*_args: object) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    service.ingest.side_effect = service.query.side_effect = service.status.side_effect = (
        wait_forever
    )
    app = application(settings, service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        if operation == "ingest":
            response = await client.put(
                f"/api/v1/ai/documents/{uuid4()}", json={"title": "T", "text": "Text"}
            )
        elif operation == "status":
            response = await client.get(f"/api/v1/ai/documents/{uuid4()}")
        else:
            response = await client.post("/api/v1/ai/query", json={"question": "Q"})
    assert response.status_code == 503
    assert response.json()["error"]["message"] == "AI request exceeded the time limit"
    assert cancelled.is_set()


async def test_enabled_resource_dependency_yields_and_closes_per_request(
    monkeypatch: MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None, ai_enabled=True)
    resources = AIResources(
        models=create_autospec(ModelProvider, instance=True),
        vectors=create_autospec(VectorStore, instance=True),
        knowledge=create_autospec(KnowledgeStore, instance=True),
    )
    calls: list[str] = []

    @asynccontextmanager
    async def managed(_settings: object) -> AsyncGenerator[AIResources]:
        calls.append("open")
        try:
            yield resources
        finally:
            calls.append("closed")

    monkeypatch.setattr(router, "ai_resources", managed)
    async for provided in router.resources_from_settings(settings):
        assert provided is resources
    assert calls == ["open", "closed"]


async def test_resources_override_is_used_by_real_service_without_external_calls() -> None:
    settings = Settings(_env_file=None, ai_enabled=True)
    session = create_autospec(AsyncSession, instance=True)
    session.scalar.return_value = None
    models = create_autospec(ModelProvider, instance=True)
    vectors = create_autospec(VectorStore, instance=True)
    knowledge = create_autospec(KnowledgeStore, instance=True)
    resources = AIResources(models=models, vectors=vectors, knowledge=knowledge)
    app = application(settings)
    app.dependency_overrides[router.resources_from_settings] = lambda: resources
    app.dependency_overrides[database_session] = lambda: session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/ai/documents/{uuid4()}")
    assert response.status_code == 404
    session.scalar.assert_awaited_once()
    assert not models.mock_calls
    assert not vectors.mock_calls
    assert not knowledge.mock_calls


async def test_service_dependency_wires_request_session_and_embedding_identity(
    test_settings: Settings,
) -> None:
    session = create_autospec(AsyncSession, instance=True)
    resources = AIResources(
        models=create_autospec(ModelProvider, instance=True),
        vectors=create_autospec(VectorStore, instance=True),
        knowledge=create_autospec(KnowledgeStore, instance=True),
    )
    async for service in router.service(session, test_settings, resources):
        assert service.session is session
        assert service.models is resources.models
        assert service.vectors is resources.vectors
        assert service.knowledge is resources.knowledge
        assert service.collection == test_settings.ai.ai_qdrant_collection
        assert service.embedding_profile == test_settings.ai.embedding_profile


def application_with_empty_retrieval(settings: Settings) -> FastAPI:
    """Exercise the actual service and LangGraph with deterministic model/store ports."""
    models = create_autospec(ModelProvider, instance=True)
    models.embed.return_value = [[1.0]]
    vectors = create_autospec(VectorStore, instance=True)
    vectors.search.return_value = []
    resources = AIResources(
        models=models,
        vectors=vectors,
        knowledge=create_autospec(KnowledgeStore, instance=True),
    )
    session = create_autospec(AsyncSession, instance=True)
    app = application(settings)
    app.dependency_overrides[router.resources_from_settings] = lambda: resources
    app.dependency_overrides[database_session] = lambda: session
    return app


@pytest.mark.parametrize("export_status", [200, 503])
async def test_trace_export_finishes_before_response_and_failures_leave_ai_response_unchanged(
    monkeypatch: MonkeyPatch, caplog: LogCaptureFixture, export_status: int
) -> None:
    settings = Settings(
        _env_file=None,
        ai_enabled=True,
        langfuse_enabled=True,
        langfuse_base_url="https://langfuse.test",
        langfuse_public_key=SecretStr("pk-lf-router-test"),
        langfuse_secret_key=SecretStr(_SECRET),
    )
    events: list[str] = []
    requests: list[httpx.Request] = []
    clients: list[AsyncClient] = []

    async def export(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        events.append("export_started")
        await asyncio.sleep(0)
        events.append("export_finished")
        return httpx.Response(export_status, text=_SECRET if export_status != 200 else "{}")

    def client_factory(
        *,
        base_url: str,
        auth: httpx.Auth,
        headers: dict[str, str],
        timeout: httpx.Timeout,
        follow_redirects: bool,
    ) -> AsyncClient:
        client = AsyncClient(
            base_url=base_url,
            auth=auth,
            headers=headers,
            timeout=timeout,
            follow_redirects=follow_redirects,
            transport=httpx.MockTransport(export),
        )
        clients.append(client)
        return client

    monkeypatch.setattr(observability.httpx, "AsyncClient", client_factory)
    app = application_with_empty_retrieval(settings)

    async def recorded_app(scope: Scope, receive: Receive, send: Send) -> None:
        async def record(message: Message) -> None:
            if message["type"] == "http.response.start":
                events.append("response_started")
                assert all(client.is_closed for client in clients)
            await send(message)

        await app(scope, receive, record)

    question = "PRIVATE_QUESTION_MUST_NOT_APPEAR_IN_TRACE"
    async with AsyncClient(
        transport=ASGITransport(app=recorded_app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/ai/query", json={"question": question})

    assert response.status_code == 200
    assert response.json() == {"answer": NO_SOURCES_ANSWER, "sources": [], "facts": []}
    assert events == ["export_started", "export_finished", "response_started"]
    assert len(requests) == len(clients) == 1
    assert str(requests[0].url) == "https://langfuse.test/api/public/otel/v1/traces"
    assert requests[0].headers["x-langfuse-ingestion-version"] == "4"
    assert question not in requests[0].content.decode()
    assert _SECRET not in requests[0].content.decode()
    assert _SECRET not in response.text
    assert _SECRET not in caplog.text
    if export_status == 503:
        assert "Langfuse trace export failed" in caplog.text


async def test_disabled_observability_creates_no_http_client_for_a_successful_ai_request(
    monkeypatch: MonkeyPatch,
) -> None:
    clients = Mock(side_effect=AssertionError("Disabled observability must not construct a client"))
    monkeypatch.setattr(observability.httpx, "AsyncClient", clients)
    app = application_with_empty_retrieval(Settings(_env_file=None, ai_enabled=True))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/ai/query", json={"question": "Question"})
    assert response.status_code == 200
    assert response.json()["answer"] == NO_SOURCES_ANSWER
    clients.assert_not_called()
