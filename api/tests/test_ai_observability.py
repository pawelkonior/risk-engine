import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.context import reset_request_id, set_request_id
from app.core.errors import DependencyUnavailableError
from app.core.settings.langfuse import LangfuseSettings
from app.modules.ai.contracts import KnowledgeStore, ModelProvider, VectorStore
from app.modules.ai.domain import DocumentInput, GraphContext, QueryInput, VectorHit
from app.modules.ai.service import AiService, prepare_document
from app.platform.ai.observability import LangfuseObserver, langfuse_observer
from app.platform.persistence import Base


def attributes(span: dict[str, Any]) -> dict[str, Any]:
    return {
        attribute["key"]: next(iter(attribute["value"].values()))
        for attribute in span["attributes"]
    }


def exported_spans(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return payload["resourceSpans"][0]["scopeSpans"][0]["spans"]


async def test_nested_spans_keep_hierarchy_and_export_only_safe_metadata() -> None:
    requests: list[httpx.Request] = []

    def export(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(
        base_url="http://langfuse", transport=httpx.MockTransport(export)
    ) as client:
        observer = LangfuseObserver(client, chat_model="local-model")
        token = set_request_id("request-123")
        try:
            with observer.span(
                "ai.query",
                metadata={"namespace": "demo", "api_key": "forbidden-key", "limit": 1.5},
                input={"question": "private-question"},
            ) as root:
                with observer.span("ai.generate", kind="generation") as generation:
                    generation.update(output="private-answer")
                root.update(
                    metadata={"source_count": 1, "idempotent": False, "hit_count": float("nan")}
                )
            await observer.flush()
            await observer.flush()
        finally:
            reset_request_id(token)
    assert len(requests) == 1
    assert requests[0].url.path == "/api/public/otel/v1/traces"
    text = requests[0].content.decode()
    assert "private-question" not in text and "private-answer" not in text
    assert "forbidden-key" not in text and "NaN" not in text
    child, root = exported_spans(json.loads(text))
    assert child["traceId"] == root["traceId"]
    assert child["parentSpanId"] == root["spanId"]
    assert "parentSpanId" not in root
    assert len(root["traceId"]) == 32 and len(root["spanId"]) == 16
    assert int(root["endTimeUnixNano"]) >= int(root["startTimeUnixNano"])
    root_attributes = attributes(root)
    assert root_attributes["langfuse.observation.metadata.request_id"] == "request-123"
    assert root_attributes["langfuse.observation.metadata.source_count"] == "1"
    assert root_attributes["langfuse.observation.metadata.idempotent"] is False
    assert root_attributes["langfuse.observation.metadata.limit"] == 1.5
    assert attributes(child)["langfuse.observation.model.name"] == "local-model"


async def test_content_is_explicit_bounded_and_exceptions_never_capture_messages() -> None:
    payloads: list[dict[str, Any]] = []

    def export(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200)

    async with httpx.AsyncClient(
        base_url="http://langfuse", transport=httpx.MockTransport(export)
    ) as client:
        observer = LangfuseObserver(client, capture_content=True, embedding_model="embedding-model")
        with observer.span("ai.ingest", input={"text": "allowed-content"}) as root:
            root.update(output={"status": "ready"}, metadata={"namespace": "n" * 300})
            with observer.span("ai.embed", kind="embedding", input="x" * 40_000):
                pass
            with observer.span("invalid-content", input=object()) as invalid:
                invalid.update(output=float("nan"))
            with (
                pytest.raises(RuntimeError, match="secret-provider-error"),
                observer.span("failed"),
            ):
                raise RuntimeError("secret-provider-error")
        await observer.flush()
    serialized = json.dumps(payloads)
    assert "allowed-content" in serialized and "secret-provider-error" not in serialized
    spans = {span["name"]: span for span in exported_spans(payloads[0])}
    assert spans["failed"]["status"] == {"code": 2}
    assert attributes(spans["failed"])["error.type"] == "RuntimeError"
    assert attributes(spans["failed"])["langfuse.observation.level"] == "ERROR"
    embed_attributes = attributes(spans["ai.embed"])
    assert embed_attributes["langfuse.observation.model.name"] == "embedding-model"
    assert json.loads(embed_attributes["langfuse.observation.input"])["truncated"] is True
    assert len(embed_attributes["langfuse.observation.input"].encode()) <= 16_384
    assert "langfuse.observation.input" not in attributes(spans["invalid-content"])
    assert "langfuse.observation.output" not in attributes(spans["invalid-content"])
    assert len(attributes(spans["ai.ingest"])["langfuse.observation.metadata.namespace"]) == 256


async def test_disabled_observer_and_span_limit_do_not_accumulate_unbounded_data() -> None:
    disabled = LangfuseObserver()
    with disabled.span("ignored", input="private") as observation:
        observation.update(output="private")
    await disabled.flush()
    payloads: list[dict[str, Any]] = []

    def export(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200)

    async with httpx.AsyncClient(
        base_url="http://langfuse", transport=httpx.MockTransport(export)
    ) as client:
        observer = LangfuseObserver(client)
        for _ in range(70):
            with observer.span("bounded"):
                pass
        await observer.flush()
        with observer.span("next-request"):
            pass
        await observer.flush()
    assert len(exported_spans(payloads[0])) == 64
    assert len(exported_spans(payloads[1])) == 1


@pytest.mark.parametrize("failure", ["http", "network", "timeout", "unexpected"])
async def test_export_is_bounded_and_fail_open(
    failure: str, caplog: pytest.LogCaptureFixture
) -> None:
    calls = 0

    async def export(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure == "network":
            raise httpx.ConnectError("secret-host-and-key", request=request)
        if failure == "unexpected":
            raise ValueError("secret-serialization-error")
        if failure == "timeout":
            await asyncio.Event().wait()
        return httpx.Response(500, text="secret-provider-response")

    async with httpx.AsyncClient(
        base_url="http://langfuse", transport=httpx.MockTransport(export)
    ) as client:
        observer = LangfuseObserver(client, timeout_seconds=0.01)
        with observer.span("request"):
            pass
        with caplog.at_level(logging.WARNING):
            await observer.flush()
            await observer.flush()
    assert calls == 1
    assert "Langfuse trace export failed" in caplog.text
    assert "secret" not in caplog.text


async def test_export_preserves_cancellation_semantics() -> None:
    async def export(_request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError()

    async with httpx.AsyncClient(
        base_url="http://langfuse", transport=httpx.MockTransport(export)
    ) as client:
        observer = LangfuseObserver(client)
        with observer.span("cancelled"):
            pass
        with pytest.raises(asyncio.CancelledError):
            await observer.flush()


@pytest.mark.parametrize("rejected_spans", [2, "2"])
async def test_partial_success_reports_safe_count_without_retry_or_server_message(
    rejected_spans: int | str, caplog: pytest.LogCaptureFixture
) -> None:
    calls = 0

    def export(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "partialSuccess": {
                    "rejectedSpans": rejected_spans,
                    "errorMessage": "secret-server-response",
                }
            },
        )

    async with httpx.AsyncClient(
        base_url="http://langfuse", transport=httpx.MockTransport(export)
    ) as client:
        observer = LangfuseObserver(client)
        with observer.span("request"):
            pass
        with caplog.at_level(logging.WARNING):
            await observer.flush()
            await observer.flush()
    assert calls == 1
    assert "Langfuse trace export rejected spans" in caplog.text
    assert caplog.records[-1].__dict__["rejected_span_count"] == 2
    assert "secret-server-response" not in caplog.text


@pytest.mark.parametrize(
    "body", [{}, {"partialSuccess": {}}, {"partialSuccess": {"rejectedSpans": "0"}}]
)
async def test_successful_otlp_json_responses_need_no_warning(
    body: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    async with httpx.AsyncClient(
        base_url="http://langfuse",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=body)),
    ) as client:
        observer = LangfuseObserver(client)
        with observer.span("request"):
            pass
        with caplog.at_level(logging.WARNING):
            await observer.flush()
    assert "Langfuse" not in caplog.text


@pytest.mark.parametrize("body", ["not-json", {"partialSuccess": {"rejectedSpans": str(2**80)}}])
async def test_invalid_otlp_responses_remain_fail_open(
    body: str | dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    def export(_request: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(200, text=body)
            if isinstance(body, str)
            else httpx.Response(200, json=body)
        )

    async with httpx.AsyncClient(
        base_url="http://langfuse", transport=httpx.MockTransport(export)
    ) as client:
        observer = LangfuseObserver(client)
        with observer.span("request"):
            pass
        with caplog.at_level(logging.WARNING):
            await observer.flush()
    assert "Langfuse trace export failed" in caplog.text


async def test_observer_context_is_isolated_between_concurrent_requests() -> None:
    payloads: list[dict[str, Any]] = []

    def export(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200)

    async with httpx.AsyncClient(
        base_url="http://langfuse", transport=httpx.MockTransport(export)
    ) as client:
        observers = [LangfuseObserver(client), LangfuseObserver(client)]
        barrier = asyncio.Event()
        arrivals = 0

        async def request(observer: LangfuseObserver, namespace: str) -> None:
            nonlocal arrivals
            with observer.span("root", metadata={"namespace": namespace}):
                arrivals += 1
                if arrivals == 2:
                    barrier.set()
                await barrier.wait()
                with observer.span("child"):
                    pass
            await observer.flush()

        await asyncio.gather(request(observers[0], "first"), request(observers[1], "second"))
    first, second = [exported_spans(payload) for payload in payloads]
    assert first[0]["traceId"] != second[0]["traceId"]
    for spans in (first, second):
        assert spans[0]["parentSpanId"] == spans[1]["spanId"]
        assert (
            attributes(spans[0])["langfuse.observation.metadata.namespace"]
            == attributes(spans[1])["langfuse.observation.metadata.namespace"]
        )


async def test_factory_flushes_before_close_and_is_lazy_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients: list[httpx.AsyncClient] = []
    requests: list[httpx.Request] = []
    original = httpx.AsyncClient

    def export(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert not clients[0].is_closed
        return httpx.Response(200)

    def client_factory(**kwargs: Any) -> httpx.AsyncClient:
        client = original(**kwargs, transport=httpx.MockTransport(export))
        clients.append(client)
        return client

    monkeypatch.setattr("app.platform.ai.observability.httpx.AsyncClient", client_factory)
    async with langfuse_observer(Settings(_env_file=None).langfuse) as observer:
        with observer.span("disabled"):
            pass
    assert clients == []
    settings = Settings(
        _env_file=None,
        langfuse_enabled=True,
        langfuse_public_key="pk-test",
        langfuse_secret_key="sk-test",
    ).langfuse
    with pytest.raises(ValueError, match="application-failure"):
        async with langfuse_observer(settings, chat_model="model") as observer:
            with observer.span("request"):
                raise ValueError("application-failure")
    assert clients[0].is_closed
    assert requests[0].headers["x-langfuse-ingestion-version"] == "4"
    assert requests[0].headers["authorization"] == "Basic cGstdGVzdDpzay10ZXN0"


async def test_factory_rejects_internally_invalid_settings_without_credentials() -> None:
    invalid = LangfuseSettings.model_construct(langfuse_enabled=True)
    with pytest.raises(ValueError, match="credentials are required"):
        async with langfuse_observer(invalid):
            pytest.fail("invalid settings must not create an observer")


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def test_actual_ingest_and_langgraph_query_emit_private_stage_traces(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    payloads: list[dict[str, Any]] = []

    def export(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200)

    models = Mock(spec=ModelProvider)
    models.embed = AsyncMock(return_value=[[1.0]])
    models.generate = AsyncMock(return_value="private-answer [S1]")
    vectors = Mock(spec=VectorStore)
    vectors.upsert = AsyncMock()
    knowledge = Mock(spec=KnowledgeStore)
    knowledge.upsert = AsyncMock()
    document_id = uuid4()
    document = DocumentInput(title="private-title", text="private-source")
    prepared = prepare_document(document_id, document)
    vectors.search = AsyncMock(
        return_value=[VectorHit(chunk_id=prepared.chunks[0].id, document_id=document_id, score=1)]
    )
    knowledge.context = AsyncMock(return_value=GraphContext(chunks=prepared.chunks))
    async with httpx.AsyncClient(
        base_url="http://langfuse", transport=httpx.MockTransport(export)
    ) as client:
        observer = LangfuseObserver(client)
        service = AiService(session, models, vectors, knowledge, "test", "local", observer=observer)
        assert (await service.ingest(document_id, document)).status == "ready"
        response = await service.query(QueryInput(question="private-question"))
        assert response.answer == "private-answer [S1]"
        models.generate.side_effect = RuntimeError("secret-model-failure")
        with pytest.raises(DependencyUnavailableError):
            await service.query(QueryInput(question="private-question"))
        await observer.flush()
    serialized = json.dumps(payloads)
    for private in [
        "private-title",
        "private-source",
        "private-question",
        "private-answer",
        "secret-model-failure",
    ]:
        assert private not in serialized
    spans = exported_spans(payloads[0])
    names = {span["name"] for span in spans}
    assert names == {
        "ai.ingest",
        "ai.embed",
        "ai.vector.upsert",
        "ai.graph.upsert",
        "ai.query",
        "ai.retrieve",
        "ai.graph",
        "ai.generate",
    }
    roots = [span for span in spans if "parentSpanId" not in span]
    assert len(roots) == 3
    assert len({span["traceId"] for span in roots}) == 3
    failed = [span for span in spans if span["status"]["code"] == 2]
    assert {attributes(span)["error.type"] for span in failed} == {
        "RuntimeError",
        "DependencyUnavailableError",
    }
