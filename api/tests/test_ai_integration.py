"""Optional local Neo4j/Qdrant checks.

Run: AI_INTEGRATION=1 uv run pytest --no-cov tests/test_ai_integration.py
"""

import os
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest
from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError
from app.modules.ai.contracts import Embedding
from app.modules.ai.domain import (
    DocumentInput,
    EntityInput,
    FactInput,
    GraphContext,
    PreparedDocument,
)
from app.modules.ai.service import prepare_document
from app.platform.ai.graph_store import Neo4jGraphStore
from app.platform.ai.vector_store import QdrantVectorStore

pytestmark = pytest.mark.skipif(
    os.environ.get("AI_INTEGRATION") != "1",
    reason="Set AI_INTEGRATION=1 to test local Neo4j and Qdrant",
)

_DIMENSIONS = 768
_PROFILE = "integration:deterministic:768"


class SessionDriver(Protocol):
    # The upstream runtime decorator leaves the **config argument untyped.
    def session(self, *, database: str) -> AsyncSession: ...


def graph_session(driver: AsyncDriver, database: str) -> AsyncSession:
    return cast(SessionDriver, driver).session(database=database)


@dataclass(frozen=True)
class Stores:
    graph: Neo4jGraphStore
    vectors: QdrantVectorStore
    driver: AsyncDriver
    client: httpx.AsyncClient
    database: str
    namespace: str
    other_namespace: str
    collection: str


@pytest.fixture
async def stores() -> AsyncGenerator[Stores]:
    settings = Settings(_env_file=None).ai
    for endpoint in (settings.ai_neo4j_uri, settings.ai_qdrant_url):
        if urlsplit(endpoint).hostname not in {"127.0.0.1", "localhost", "::1"}:
            pytest.fail("Integration tests only mutate loopback Neo4j and Qdrant services")
    identity = uuid4().hex
    namespace = f"integration_{identity}"
    namespaces = (namespace, f"{namespace}_other")
    collection = f"test_{identity}"
    headers = (
        {"api-key": settings.ai_qdrant_api_key.get_secret_value()}
        if settings.ai_qdrant_api_key is not None
        else {}
    )
    async with (
        AsyncGraphDatabase.driver(  # pyright: ignore[reportUnknownMemberType]
            settings.ai_neo4j_uri,
            auth=(settings.ai_neo4j_username, settings.ai_neo4j_password.get_secret_value()),
            telemetry_disabled=True,
            connection_timeout=5,
            max_transaction_retry_time=3,
        ) as driver,
        httpx.AsyncClient(
            base_url=settings.ai_qdrant_url, headers=headers, timeout=httpx.Timeout(15, connect=5)
        ) as client,
    ):
        graph = Neo4jGraphStore(driver, database=settings.ai_neo4j_database)
        vectors = QdrantVectorStore(client, collection, _DIMENSIONS, _PROFILE)
        try:
            # Provisioning is a release action and must also be safe to repeat.
            await graph.setup()
            await graph.setup()
            await vectors.setup()
            await vectors.setup()
            await graph.ping()
            await vectors.ping()
            yield Stores(
                graph,
                vectors,
                driver,
                client,
                settings.ai_neo4j_database,
                namespace,
                namespaces[1],
                collection,
            )
        finally:
            try:
                async with graph_session(driver, settings.ai_neo4j_database) as session:
                    for owned_namespace in namespaces:
                        result = await session.run(
                            "MATCH (node {namespace: $namespace}) DETACH DELETE node",
                            namespace=owned_namespace,
                        )
                        await result.consume()
            finally:
                response = await client.delete(f"/collections/{collection}")
                if response.status_code != 404:
                    response.raise_for_status()


def documents(namespace: str) -> tuple[PreparedDocument, PreparedDocument]:
    first_evidence = "Warsaw is the capital of Poland."
    second_evidence = "Poland is in Europe."
    first = DocumentInput(
        namespace=namespace,
        title="Cities",
        text=first_evidence + "\n" + "First source context. " * 80,
        facts=[
            FactInput(
                subject=EntityInput(name="Warsaw", kind="city"),
                predicate="capital_of",
                object=EntityInput(name="Poland", kind="country"),
                evidence=first_evidence,
            )
        ],
    )
    second = DocumentInput(
        namespace=namespace,
        title="Countries",
        text=second_evidence + "\n" + "Second source context. " * 80,
        facts=[
            FactInput(
                subject=EntityInput(name="Poland", kind="country"),
                predicate="located_in",
                object=EntityInput(name="Europe", kind="continent"),
                evidence=second_evidence,
            )
        ],
    )
    return prepare_document(uuid4(), first), prepare_document(uuid4(), second)


def embeddings(document: PreparedDocument) -> list[Embedding]:
    return [[1.0, *([0.0] * (_DIMENSIONS - 1))] for _ in document.chunks]


async def node_counts(stores: Stores) -> dict[str, int]:
    async with graph_session(stores.driver, stores.database) as session:
        result = await session.run(
            "MATCH (node {namespace: $namespace}) "
            "RETURN labels(node)[0] AS label, count(node) AS count",
            namespace=stores.namespace,
        )
        return {str(row["label"]): int(row["count"]) async for row in result}


async def test_real_graph_and_vector_upserts_preserve_provenance_and_isolation(
    stores: Stores,
) -> None:
    first, second = documents(stores.namespace)
    for document in (first, second):
        assert len(document.chunks) > 1
        await stores.graph.upsert(document)
        await stores.graph.upsert(document)
        await stores.vectors.upsert(document, embeddings(document))
        await stores.vectors.upsert(document, embeddings(document))

    assert await node_counts(stores) == {
        "Document": 2,
        "Chunk": len(first.chunks) + len(second.chunks),
        "Entity": 3,
        "Claim": 2,
    }
    async with graph_session(stores.driver, stores.database) as session:
        result = await session.run(
            "MATCH (:Document {namespace: $namespace})-[:HAS_CHUNK]->(left:Chunk)"
            "-[:NEXT]->(right:Chunk) RETURN count(*) AS count",
            namespace=stores.namespace,
        )
        row = await result.single(strict=True)
        assert row is not None
        assert row["count"] == len(first.chunks) + len(second.chunks) - 2

    requested = [second.chunks[0].id, first.chunks[0].id, first.chunks[-1].id]
    context = await stores.graph.context(stores.namespace, requested)
    assert [chunk.id for chunk in context.chunks] == requested
    assert {fact.id for fact in context.facts} == {first.facts[0].id, second.facts[0].id}
    assert await stores.graph.context(stores.other_namespace, requested) == GraphContext()

    other_profile = QdrantVectorStore(
        stores.client, stores.collection, _DIMENSIONS, "integration:different:768"
    )
    await other_profile.upsert(first, embeddings(first))
    other_document = documents(stores.other_namespace)[0]
    await stores.graph.upsert(other_document)
    await stores.vectors.upsert(other_document, embeddings(other_document))

    query_vector = [1.0, *([0.0] * (_DIMENSIONS - 1))]
    hits = await stores.vectors.search(stores.namespace, query_vector, 8)
    expected_chunks = {chunk.id for doc in (first, second) for chunk in doc.chunks}
    assert len(hits) == len(expected_chunks)
    assert {hit.chunk_id for hit in hits} == expected_chunks
    assert {hit.document_id for hit in hits} == {first.id, second.id}
    profile_hits = await other_profile.search(stores.namespace, query_vector, 8)
    assert {hit.chunk_id for hit in profile_hits} == {chunk.id for chunk in first.chunks}
    namespace_hits = await stores.vectors.search(stores.other_namespace, query_vector, 8)
    assert {hit.document_id for hit in namespace_hits} == {other_document.id}
    assert await stores.vectors.search(f"missing_{uuid4().hex}", query_vector, 8) == []

    with pytest.raises(ConflictError, match="different content"):
        await stores.graph.upsert(first.model_copy(update={"content_hash": "f" * 64}))
    assert await stores.graph.context(stores.namespace, requested) == context


async def test_real_delete_keeps_other_document_and_shared_entity(stores: Stores) -> None:
    first, second = documents(stores.namespace)
    assert first.facts[0].object_id == second.facts[0].subject_id
    for document in (first, second):
        await stores.graph.upsert(document)
        await stores.vectors.upsert(document, embeddings(document))

    await stores.graph.delete(stores.namespace, first.id)
    await stores.graph.delete(stores.namespace, first.id)
    await stores.vectors.delete(stores.namespace, first.id)
    await stores.vectors.delete(stores.namespace, first.id)

    assert (
        await stores.graph.context(stores.namespace, [chunk.id for chunk in first.chunks])
        == GraphContext()
    )
    remaining = await stores.graph.context(stores.namespace, [chunk.id for chunk in second.chunks])
    assert remaining.chunks == second.chunks
    assert remaining.facts == second.facts
    assert await node_counts(stores) == {
        "Document": 1,
        "Chunk": len(second.chunks),
        "Entity": 2,
        "Claim": 1,
    }
    hits = await stores.vectors.search(stores.namespace, [1.0, *([0.0] * (_DIMENSIONS - 1))], 8)
    assert len(hits) == len(second.chunks)
    assert {hit.document_id for hit in hits} == {second.id}
