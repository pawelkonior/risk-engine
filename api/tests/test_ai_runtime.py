from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, nullcontext
from unittest.mock import AsyncMock, Mock, create_autospec

import httpx
import pytest
from neo4j import AsyncDriver
from pydantic import SecretStr
from pytest import MonkeyPatch

from app.core.config import Settings
from app.main import create_app
from app.modules.ai.contracts import KnowledgeStore, ModelProvider, VectorStore
from app.platform.ai import runtime, setup
from app.platform.ai.graph_store import Neo4jGraphStore
from app.platform.ai.providers import HTTPModelProvider
from app.platform.ai.runtime import AIResources
from app.platform.ai.vector_store import QdrantVectorStore


@pytest.mark.parametrize("fail", [False, True])
async def test_request_resources_are_lazy_and_all_close_on_exit(
    monkeypatch: MonkeyPatch, fail: bool
) -> None:
    def unexpected_request(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("Resource construction must not perform network I/O")

    clients = [
        httpx.AsyncClient(transport=httpx.MockTransport(unexpected_request)),
        httpx.AsyncClient(transport=httpx.MockTransport(unexpected_request)),
    ]
    client_factory = Mock(side_effect=clients)
    driver = create_autospec(AsyncDriver, instance=True)
    driver_factory = Mock(return_value=driver)
    monkeypatch.setattr(runtime.httpx, "AsyncClient", client_factory)
    monkeypatch.setattr(runtime.AsyncGraphDatabase, "driver", driver_factory)
    settings = Settings(
        _env_file=None,
        ai_qdrant_api_key=SecretStr("qdrant-test-key"),
        ai_neo4j_password=SecretStr("graph-test-password"),
    ).ai

    expected = pytest.raises(RuntimeError, match="operation failed") if fail else nullcontext()
    with expected:
        async with runtime.ai_resources(settings) as resources:
            assert isinstance(resources.models, HTTPModelProvider)
            assert isinstance(resources.vectors, QdrantVectorStore)
            assert isinstance(resources.knowledge, Neo4jGraphStore)
            assert all(not client.is_closed for client in clients)
            driver.verify_connectivity.assert_not_awaited()
            driver.session.assert_not_called()
            driver.close.assert_not_awaited()
            if fail:
                raise RuntimeError("operation failed")

    assert all(client.is_closed for client in clients)
    driver.close.assert_awaited_once_with()
    driver_factory.assert_called_once_with(
        "bolt://127.0.0.1:7687",
        auth=("neo4j", "graph-test-password"),
        connection_timeout=5,
        max_transaction_retry_time=3,
        max_connection_pool_size=4,
        notifications_min_severity="OFF",
        telemetry_disabled=True,
    )
    first = client_factory.call_args_list[0].kwargs
    second = client_factory.call_args_list[1].kwargs
    assert first == {"timeout": httpx.Timeout(40, connect=5)}
    assert second == {
        "base_url": "http://127.0.0.1:6333",
        "headers": {"api-key": "qdrant-test-key"},
        "timeout": httpx.Timeout(40, connect=5),
    }


async def test_resources_close_already_opened_clients_when_driver_creation_fails(
    monkeypatch: MonkeyPatch,
) -> None:
    clients = [httpx.AsyncClient(), httpx.AsyncClient()]
    monkeypatch.setattr(runtime.httpx, "AsyncClient", Mock(side_effect=clients))
    monkeypatch.setattr(
        runtime.AsyncGraphDatabase, "driver", Mock(side_effect=RuntimeError("driver failed"))
    )
    with pytest.raises(RuntimeError, match="driver failed"):
        async with runtime.ai_resources(Settings(_env_file=None).ai):
            pytest.fail("The failed driver must not yield resources")
    assert all(client.is_closed for client in clients)


def test_application_factory_never_constructs_ai_resources(
    monkeypatch: MonkeyPatch, test_settings: Settings
) -> None:
    clients = Mock(side_effect=AssertionError("HTTP client created during factory"))
    driver = Mock(side_effect=AssertionError("Neo4j driver created during factory"))
    monkeypatch.setattr(runtime.httpx, "AsyncClient", clients)
    monkeypatch.setattr(runtime.AsyncGraphDatabase, "driver", driver)
    create_app(test_settings)
    clients.assert_not_called()
    driver.assert_not_called()


@pytest.mark.parametrize("fail", [False, True])
async def test_explicit_setup_provisions_stores_without_model_calls(
    monkeypatch: MonkeyPatch, test_settings: Settings, fail: bool
) -> None:
    models = create_autospec(ModelProvider, instance=True)
    knowledge = create_autospec(KnowledgeStore, instance=True)
    vectors = create_autospec(VectorStore, instance=True)
    calls: list[str] = []

    async def graph_setup() -> None:
        calls.append("graph")

    async def vector_setup() -> None:
        calls.append("vectors")
        if fail:
            raise RuntimeError("setup failed")

    knowledge.setup.side_effect = graph_setup
    vectors.setup.side_effect = vector_setup

    @asynccontextmanager
    async def resources(_settings: object) -> AsyncGenerator[AIResources]:
        try:
            yield AIResources(models=models, knowledge=knowledge, vectors=vectors)
        finally:
            calls.append("closed")

    monkeypatch.setattr(setup, "ai_resources", resources)
    expected = pytest.raises(RuntimeError, match="setup failed") if fail else nullcontext()
    with expected:
        await setup.setup(test_settings)
    assert calls == ["graph", "vectors", "closed"]
    knowledge.setup.assert_awaited_once_with()
    vectors.setup.assert_awaited_once_with()
    models.embed.assert_not_awaited()
    models.generate.assert_not_awaited()


def test_setup_entrypoint_loads_settings_and_configures_logging(
    monkeypatch: MonkeyPatch, test_settings: Settings
) -> None:
    configure = Mock()
    action = AsyncMock()
    monkeypatch.setattr(setup, "Settings", Mock(return_value=test_settings))
    monkeypatch.setattr(setup, "configure_logging", configure)
    monkeypatch.setattr(setup, "setup", action)
    setup.main()
    configure.assert_called_once_with("INFO")
    action.assert_awaited_once_with(test_settings)
