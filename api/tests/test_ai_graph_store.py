from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction, AsyncResult
from pydantic import ValidationError

from app.core.errors import ConflictError
from app.modules.ai.domain import Chunk, PreparedDocument, StoredFact
from app.platform.ai.graph_store import Neo4jGraphStore


def document() -> PreparedDocument:
    document_id = uuid4()
    chunks = [
        Chunk(
            id=uuid4(),
            document_id=document_id,
            namespace="project_a",
            title="Source",
            text=f"Evidence {index}",
            position=index,
        )
        for index in range(2)
    ]
    fact = StoredFact(
        id=uuid4(),
        subject_id=uuid4(),
        subject="Alpha",
        subject_kind="concept",
        predicate="relates_to",
        object_id=uuid4(),
        object="Beta",
        object_kind="concept",
        evidence="Evidence 0",
        chunk_id=chunks[0].id,
        document_id=document_id,
        namespace="project_a",
    )
    return PreparedDocument(
        id=document_id,
        namespace="project_a",
        title="Source",
        content_hash="immutable",
        chunks=chunks,
        facts=[fact],
    )


def result(
    *, single: dict[str, object] | None = None, data: Sequence[Mapping[str, object]] | None = None
) -> AsyncMock:
    response = AsyncMock(spec=AsyncResult)
    response.single.return_value = single
    response.data.return_value = data or []
    return response


@dataclass
class GraphHarness:
    driver: Mock
    session: AsyncMock
    transaction: AsyncMock
    store: Neo4jGraphStore


def harness() -> GraphHarness:
    driver = MagicMock(spec=AsyncDriver)
    session = AsyncMock()
    transaction = AsyncMock(spec=AsyncManagedTransaction)
    driver.session.return_value.__aenter__.return_value = session

    async def execute(work: Callable[..., Awaitable[object]], *args: object) -> object:
        return await work(cast(AsyncManagedTransaction, transaction), *args)

    session.execute_write.side_effect = execute
    session.execute_read.side_effect = execute
    return GraphHarness(
        driver, session, transaction, Neo4jGraphStore(cast(AsyncDriver, driver), "neo4j")
    )


async def test_setup_is_explicit_and_creates_community_compatible_identity_constraints() -> None:
    graph = harness()
    graph.session.run.return_value = result()
    await graph.store.setup()
    assert graph.session.run.await_count == 4
    queries = [call.args[0] for call in graph.session.run.await_args_list]
    for label in ("Document", "Chunk", "Entity", "Claim"):
        assert any(
            f"(n:{label})" in query and "(n.namespace, n.id) IS UNIQUE" in query
            for query in queries
        )
    assert all("IF NOT EXISTS" in query for query in queries)
    graph.driver.session.assert_called_once_with(database="neo4j")
    graph.driver.close.assert_not_called()


async def test_ping_consumes_result_and_closes_only_its_session() -> None:
    graph = harness()
    response = result()
    graph.session.run.return_value = response
    await graph.store.ping()
    graph.session.run.assert_awaited_once_with("RETURN 1 AS ready")
    response.consume.assert_awaited_once()
    graph.driver.session.return_value.__aexit__.assert_awaited_once()
    graph.driver.close.assert_not_called()


async def test_upsert_builds_both_graphs_atomically_with_parameters_and_source_links() -> None:
    graph = harness()
    prepared = document()
    prepared.title = "A title with quotes ' and Cypher MATCH (n)"
    graph.transaction.run.side_effect = [
        result(single={"content_hash": prepared.content_hash}),
        result(single={"count": len(prepared.chunks)}),
        result(),
        result(single={"count": 1}),
    ]
    await graph.store.upsert(prepared)
    graph.session.execute_write.assert_awaited_once()
    calls = graph.transaction.run.await_args_list
    assert len(calls) == 4
    assert all(prepared.title not in call.args[0] for call in calls)
    assert all(call.kwargs["namespace"] == prepared.namespace for call in calls)
    assert all(call.kwargs["document_id"] == str(prepared.id) for call in calls)
    assert calls[0].kwargs["content_hash"] == prepared.content_hash
    assert "ON CREATE SET" in calls[0].args[0]
    assert "HAS_CHUNK" in calls[1].args[0]
    assert calls[1].kwargs["chunks"] == [chunk.model_dump(mode="json") for chunk in prepared.chunks]
    assert calls[2].kwargs["links"] == [
        {"left": str(prepared.chunks[0].id), "right": str(prepared.chunks[1].id)}
    ]
    for relation in ("SUBJECT_OF", "OBJECT", "SUPPORTED_BY", "MENTIONS"):
        assert relation in calls[3].args[0]
    assert calls[3].kwargs["facts"] == [prepared.facts[0].model_dump(mode="json")]
    assert not any("CREATE CONSTRAINT" in call.args[0] for call in calls)


async def test_upsert_without_facts_and_single_chunk_is_supported() -> None:
    graph = harness()
    prepared = document()
    prepared.chunks = prepared.chunks[:1]
    prepared.facts = []
    graph.transaction.run.side_effect = [
        result(single={"content_hash": prepared.content_hash}),
        result(single={"count": 1}),
        result(),
    ]
    await graph.store.upsert(prepared)
    assert len(graph.transaction.run.await_args_list) == 3
    assert graph.transaction.run.await_args_list[2].kwargs["links"] == []


async def test_immutable_hash_conflict_aborts_before_any_chunk_or_fact_mutation() -> None:
    graph = harness()
    graph.transaction.run.return_value = result(single={"content_hash": "different"})
    with pytest.raises(ConflictError, match="different content"):
        await graph.store.upsert(document())
    assert graph.transaction.run.await_count == 1
    graph.driver.session.return_value.__aexit__.assert_awaited_once()


@pytest.mark.parametrize("collision", ["chunk", "fact"])
async def test_foreign_id_collisions_abort_the_managed_transaction(collision: str) -> None:
    graph = harness()
    prepared = document()
    graph.transaction.run.side_effect = [
        result(single={"content_hash": prepared.content_hash}),
        result(single={"count": 1 if collision == "chunk" else 2}),
        result(),
        result(single={"count": 0}),
    ]
    with pytest.raises(ConflictError, match="another document"):
        await graph.store.upsert(prepared)


@pytest.mark.parametrize(
    "invalid",
    [
        "empty",
        "duplicate",
        "chunk_namespace",
        "chunk_document",
        "fact_namespace",
        "fact_document",
        "fact_chunk",
    ],
)
async def test_upsert_rejects_inconsistent_source_ownership_before_connecting(invalid: str) -> None:
    graph = harness()
    prepared = document()
    if invalid == "empty":
        prepared.chunks = []
    elif invalid == "duplicate":
        prepared.chunks.append(prepared.chunks[0])
    elif invalid == "chunk_namespace":
        prepared.chunks[0].namespace = "foreign"
    elif invalid == "chunk_document":
        prepared.chunks[0].document_id = uuid4()
    elif invalid == "fact_namespace":
        prepared.facts[0].namespace = "foreign"
    elif invalid == "fact_document":
        prepared.facts[0].document_id = uuid4()
    else:
        prepared.facts[0].chunk_id = uuid4()
    with pytest.raises(ValueError, match="belong"):
        await graph.store.upsert(prepared)
    graph.driver.session.assert_not_called()


async def test_context_restores_relevance_order_and_reads_only_owned_cited_facts() -> None:
    graph = harness()
    prepared = document()
    graph.transaction.run.side_effect = [
        result(
            data=[{"chunk": chunk.model_dump(mode="json")} for chunk in reversed(prepared.chunks)]
        ),
        result(data=[{"fact": prepared.facts[0].model_dump(mode="json")}]),
    ]
    context = await graph.store.context(prepared.namespace, [chunk.id for chunk in prepared.chunks])
    assert context.chunks == prepared.chunks
    assert context.facts == prepared.facts
    calls = graph.transaction.run.await_args_list
    assert len(calls) == 2
    assert all(call.kwargs["namespace"] == prepared.namespace for call in calls)
    assert all(
        call.kwargs["chunk_ids"] == [str(chunk.id) for chunk in prepared.chunks] for call in calls
    )
    assert "HAS_CHUNK" in calls[0].args[0]
    assert "SUPPORTED_BY" in calls[1].args[0]
    assert "LIMIT 32" in calls[1].args[0]
    assert "claim.document_id = document.id" in calls[1].args[0]


async def test_context_omits_missing_chunks_and_deduplicates_inputs() -> None:
    graph = harness()
    prepared = document()
    graph.transaction.run.side_effect = [
        result(data=[{"chunk": prepared.chunks[0].model_dump(mode="json")}]),
        result(),
    ]
    context = await graph.store.context(
        prepared.namespace, [prepared.chunks[0].id, uuid4(), prepared.chunks[0].id]
    )
    assert context.chunks == prepared.chunks[:1]
    assert graph.transaction.run.await_args_list[1].kwargs["chunk_ids"] == [
        str(prepared.chunks[0].id)
    ]


async def test_empty_or_missing_context_returns_no_facts() -> None:
    graph = harness()
    assert (await graph.store.context("n", [])).chunks == []
    graph.driver.session.assert_not_called()
    graph.transaction.run.return_value = result()
    assert (await graph.store.context("n", [uuid4()])).facts == []
    assert graph.transaction.run.await_count == 1


@pytest.mark.parametrize("field", ["namespace", "id"])
async def test_context_rejects_chunks_outside_the_requested_scope(field: str) -> None:
    graph = harness()
    prepared = document()
    raw = prepared.chunks[0].model_dump(mode="json")
    raw[field] = "foreign" if field == "namespace" else str(uuid4())
    graph.transaction.run.return_value = result(data=[{"chunk": raw}])
    with pytest.raises(ValueError, match="outside"):
        await graph.store.context(prepared.namespace, [prepared.chunks[0].id])


@pytest.mark.parametrize("invalid", ["namespace", "document_id", "chunk_id", "excess"])
async def test_context_rejects_orphaned_foreign_or_excessive_facts(invalid: str) -> None:
    graph = harness()
    prepared = document()
    raw = prepared.facts[0].model_dump(mode="json")
    if invalid != "excess":
        raw[invalid] = "foreign" if invalid == "namespace" else str(uuid4())
    facts = [{"fact": raw}] * (33 if invalid == "excess" else 1)
    graph.transaction.run.side_effect = [
        result(data=[{"chunk": prepared.chunks[0].model_dump(mode="json")}]),
        result(data=facts),
    ]
    with pytest.raises(ValueError, match="owned source"):
        await graph.store.context(prepared.namespace, [prepared.chunks[0].id])


async def test_malformed_database_records_fail_validation() -> None:
    graph = harness()
    graph.transaction.run.return_value = result(single={})
    with pytest.raises(ValidationError):
        await graph.store.upsert(document())
    graph.transaction.run.return_value = result(data=[{"chunk": {"id": "invalid"}}])
    with pytest.raises(ValidationError):
        await graph.store.context("n", [uuid4()])


async def test_delete_is_atomic_scoped_and_preserves_entities_with_remaining_links() -> None:
    graph = harness()
    graph.transaction.run.return_value = result()
    document_id = uuid4()
    namespace = "value ' MATCH (n)"
    await graph.store.delete(namespace, document_id)
    graph.session.execute_write.assert_awaited_once()
    call = graph.transaction.run.await_args
    assert call is not None
    assert call.kwargs == {"namespace": namespace, "document_id": str(document_id)}
    query = call.args[0]
    assert namespace not in query
    assert "chunk.document_id = $document_id" in query
    assert "Claim {namespace: $namespace, document_id: $document_id}" in query
    assert "WHERE NOT (entity)--()" in query
    assert "collect(DISTINCT" in query
