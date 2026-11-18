import json
from collections.abc import Callable
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.modules.ai.contracts import Embedding
from app.modules.ai.domain import Chunk, PreparedDocument
from app.platform.ai.vector_store import QdrantVectorStore


def document() -> PreparedDocument:
    document_id = uuid4()
    return PreparedDocument(
        id=document_id,
        namespace="project_a",
        title="Source",
        content_hash="immutable",
        chunks=[
            Chunk(
                id=uuid4(),
                document_id=document_id,
                namespace="project_a",
                title="Source",
                text="A source chunk",
                position=0,
            )
        ],
        facts=[],
    )


def collection_response(size: int = 2, distance: str = "Cosine") -> dict[str, object]:
    return {
        "status": "ok",
        "result": {"config": {"params": {"vectors": {"size": size, "distance": distance}}}},
        "time": 0.001,
    }


def write_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={"status": "ok", "result": {"operation_id": 1, "status": "completed"}},
    )


def client_with(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://vectors.example",
        headers={"api-key": "secret"},
        transport=httpx.MockTransport(handler),
    )


async def test_setup_creates_collection_and_filter_indexes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(404)
        if request.url.path == "/collections/chunks":
            return httpx.Response(200, json={"result": True, "status": "ok"})
        return write_response()

    async with client_with(handler) as client:
        await QdrantVectorStore(client, "chunks", 2, "ollama-model").setup()
        assert not client.is_closed
    assert [request.method for request in requests] == ["GET", "PUT", "PUT", "PUT", "PUT"]
    assert json.loads(requests[1].content) == {"vectors": {"size": 2, "distance": "Cosine"}}
    assert [json.loads(request.content)["field_name"] for request in requests[2:]] == [
        "namespace",
        "document_id",
        "embedding_profile",
    ]
    assert all(request.url.params["wait"] == "true" for request in requests[2:])
    assert all(request.headers["api-key"] == "secret" for request in requests)


async def test_setup_preserves_existing_collection_and_ping_validates_configuration() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return (
            httpx.Response(200, json=collection_response())
            if request.method == "GET"
            else write_response()
        )

    async with client_with(handler) as client:
        store = QdrantVectorStore(client, "chunks", 2, "profile")
        await store.setup()
        await store.ping()
    assert sum(request.method == "GET" for request in requests) == 2
    assert all(
        request.url.path.endswith("/index") for request in requests if request.method == "PUT"
    )


@pytest.mark.parametrize("size,distance", [(3, "Cosine"), (2, "Dot")])
async def test_setup_rejects_incompatible_collection_without_mutating_it(
    size: int, distance: str
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=collection_response(size, distance))

    async with client_with(handler) as client:
        with pytest.raises(ValueError):
            await QdrantVectorStore(client, "chunks", 2, "profile").setup()
    assert len(requests) == 1


@pytest.mark.parametrize(
    "collection,size,profile", [("../other", 2, "p"), ("ok", 0, "p"), ("ok", 2, " ")]
)
async def test_constructor_rejects_invalid_configuration(
    collection: str, size: int, profile: str
) -> None:
    async with client_with(lambda _request: write_response()) as client:
        with pytest.raises(ValueError):
            QdrantVectorStore(client, collection, size, profile)


@pytest.mark.parametrize("embedding", [[0.1, 0.2], {"text": "a source", "model": "cloud-model"}])
async def test_upsert_uses_explicit_vectors_or_cloud_inference_and_stable_profile_ids(
    embedding: Embedding,
) -> None:
    requests: list[httpx.Request] = []
    prepared = document()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return write_response()

    async with client_with(handler) as client:
        store = QdrantVectorStore(client, "chunks", 2, "profile-a")
        await store.upsert(prepared, [embedding])
        await store.upsert(prepared, [embedding])
        await QdrantVectorStore(client, "chunks", 2, "profile-b").upsert(prepared, [embedding])
    first, second, other = [json.loads(request.content)["points"][0] for request in requests]
    assert first == second
    assert first["id"] != other["id"]
    assert first["vector"] == embedding
    assert first["payload"] == {
        "namespace": prepared.namespace,
        "document_id": str(prepared.id),
        "chunk_id": str(prepared.chunks[0].id),
        "embedding_profile": "profile-a",
    }
    assert all(request.url.path == "/collections/chunks/points" for request in requests)
    assert all(request.url.params["wait"] == "true" for request in requests)


@pytest.mark.parametrize(
    "embeddings",
    [[], [[0.1]], [[float("nan"), 0.1]], [{"text": "x"}], [{"text": "", "model": "x"}]],
)
async def test_upsert_rejects_missing_or_invalid_embeddings(embeddings: list[Embedding]) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return write_response()

    async with client_with(handler) as client:
        with pytest.raises(ValueError):
            await QdrantVectorStore(client, "chunks", 2, "profile").upsert(document(), embeddings)
    assert requests == []


async def test_upsert_rejects_foreign_or_empty_document_chunks() -> None:
    prepared = document()
    async with client_with(lambda _request: write_response()) as client:
        store = QdrantVectorStore(client, "chunks", 2, "profile")
        for field, value in (("namespace", "foreign"), ("document_id", uuid4())):
            invalid = prepared.model_copy(deep=True)
            setattr(invalid.chunks[0], field, value)
            with pytest.raises(ValueError, match="belong"):
                await store.upsert(invalid, [[0.1, 0.2]])
        with pytest.raises(ValueError, match="one embedding"):
            await store.upsert(prepared.model_copy(update={"chunks": []}), [])


async def test_search_filters_namespace_profile_and_returns_source_identifiers() -> None:
    prepared = document()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "result": {
                    "points": [
                        {
                            "id": str(uuid4()),
                            "version": 1,
                            "score": 0.95,
                            "payload": {
                                "namespace": prepared.namespace,
                                "embedding_profile": "profile",
                                "document_id": str(prepared.id),
                                "chunk_id": str(prepared.chunks[0].id),
                            },
                        }
                    ]
                },
            },
        )

    async with client_with(handler) as client:
        hits = await QdrantVectorStore(client, "chunks", 2, "profile").search(
            prepared.namespace, {"text": "question", "model": "cloud-model"}, 3
        )
    assert len(hits) == 1
    assert hits[0].chunk_id == prepared.chunks[0].id
    assert hits[0].document_id == prepared.id
    body = json.loads(requests[0].content)
    assert body["query"] == {"text": "question", "model": "cloud-model"}
    assert body["limit"] == 3
    assert body["filter"] == {
        "must": [
            {"key": "namespace", "match": {"value": prepared.namespace}},
            {"key": "embedding_profile", "match": {"value": "profile"}},
        ]
    }
    assert body["with_vector"] is False
    assert requests[0].url.path == "/collections/chunks/points/query"


@pytest.mark.parametrize(
    "field,value", [("namespace", "foreign"), ("embedding_profile", "foreign")]
)
async def test_search_fails_closed_for_out_of_scope_results(field: str, value: str) -> None:
    payload = {
        "namespace": "project_a",
        "embedding_profile": "profile",
        "document_id": str(uuid4()),
        "chunk_id": str(uuid4()),
    }
    payload[field] = value
    async with client_with(
        lambda _request: httpx.Response(
            200,
            json={
                "status": "ok",
                "result": {"points": [{"id": str(uuid4()), "score": 1, "payload": payload}]},
            },
        )
    ) as client:
        with pytest.raises(ValueError, match="outside"):
            await QdrantVectorStore(client, "chunks", 2, "profile").search(
                "project_a", [0.1, 0.2], 1
            )


@pytest.mark.parametrize("limit", [0, 9])
async def test_search_rejects_unbounded_limits(limit: int) -> None:
    async with client_with(lambda _request: write_response()) as client:
        with pytest.raises(ValueError, match="limit"):
            await QdrantVectorStore(client, "chunks", 2, "profile").search("n", [0.1, 0.2], limit)


async def test_search_rejects_invalid_and_excessive_responses() -> None:
    point = {
        "id": str(uuid4()),
        "score": 1,
        "payload": {
            "namespace": "n",
            "embedding_profile": "p",
            "document_id": str(uuid4()),
            "chunk_id": str(uuid4()),
        },
    }
    async with client_with(
        lambda _request: httpx.Response(
            200, json={"status": "ok", "result": {"points": [point, point]}}
        )
    ) as client:
        with pytest.raises(ValueError, match="more points"):
            await QdrantVectorStore(client, "chunks", 2, "p").search("n", [0.1, 0.2], 1)
    async with client_with(
        lambda _request: httpx.Response(200, json={"status": "ok", "result": {}})
    ) as client:
        with pytest.raises(ValidationError):
            await QdrantVectorStore(client, "chunks", 2, "p").search("n", [0.1, 0.2], 1)


async def test_delete_is_scoped_and_does_not_create_schema() -> None:
    requests: list[httpx.Request] = []
    document_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return write_response()

    async with client_with(handler) as client:
        await QdrantVectorStore(client, "chunks", 2, "p").delete("n", document_id)
    assert len(requests) == 1
    assert requests[0].url.path == "/collections/chunks/points/delete"
    assert json.loads(requests[0].content) == {
        "filter": {
            "must": [
                {"key": "namespace", "match": {"value": "n"}},
                {"key": "embedding_profile", "match": {"value": "p"}},
                {"key": "document_id", "match": {"value": str(document_id)}},
            ]
        }
    }


async def test_http_errors_and_invalid_write_responses_are_not_hidden() -> None:
    async with client_with(lambda _request: httpx.Response(503)) as client:
        store = QdrantVectorStore(client, "chunks", 2, "p")
        with pytest.raises(httpx.HTTPStatusError):
            await store.ping()
        with pytest.raises(httpx.HTTPStatusError):
            await store.setup()
    async with client_with(
        lambda _request: httpx.Response(200, json={"status": "error"})
    ) as client:
        with pytest.raises(ValidationError):
            await QdrantVectorStore(client, "chunks", 2, "p").delete("n", uuid4())
