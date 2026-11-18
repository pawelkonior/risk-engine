"""Small asynchronous Qdrant REST adapter shared by local and managed clusters."""

import math
import re
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from pydantic import BaseModel, Field

from app.modules.ai.contracts import Embedding
from app.modules.ai.domain import PreparedDocument, VectorHit


class _VectorConfiguration(BaseModel):
    size: int
    distance: Literal["Cosine"]


class _CollectionParameters(BaseModel):
    vectors: _VectorConfiguration


class _CollectionConfiguration(BaseModel):
    params: _CollectionParameters


class _CollectionResult(BaseModel):
    config: _CollectionConfiguration


class _CollectionResponse(BaseModel):
    status: Literal["ok"]
    result: _CollectionResult


class _BooleanResponse(BaseModel):
    status: Literal["ok"]
    result: Literal[True]


class _WriteResult(BaseModel):
    status: Literal["acknowledged", "completed"]


class _WriteResponse(BaseModel):
    status: Literal["ok"]
    result: _WriteResult


class _PointPayload(BaseModel):
    namespace: str
    document_id: UUID
    chunk_id: UUID
    embedding_profile: str


class _Point(BaseModel):
    id: UUID
    score: float = Field(allow_inf_nan=False)
    payload: _PointPayload


class _QueryResult(BaseModel):
    points: list[_Point]


class _QueryResponse(BaseModel):
    status: Literal["ok"]
    result: _QueryResult


class QdrantVectorStore:
    """Use an externally owned HTTP client; never initialize schema during requests."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        collection: str,
        dimensions: int,
        embedding_profile: str,
    ) -> None:
        if re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", collection) is None:
            raise ValueError("invalid Qdrant collection name")
        if dimensions < 1 or not embedding_profile.strip():
            raise ValueError("embedding dimensions and profile must be configured")
        self._client = client
        self._path = f"/collections/{collection}"
        self._dimensions = dimensions
        self._profile = embedding_profile

    def _configuration(self, response: httpx.Response) -> None:
        response.raise_for_status()
        configuration = _CollectionResponse.model_validate(response.json())
        if configuration.result.config.params.vectors.size != self._dimensions:
            raise ValueError("Qdrant collection dimensions differ from the embedding configuration")

    async def setup(self) -> None:
        """Explicitly provision a collection and its filter indexes, or validate it."""
        response = await self._client.get(self._path)
        if response.status_code == 404:
            created = await self._client.put(
                self._path,
                json={"vectors": {"size": self._dimensions, "distance": "Cosine"}},
            )
            created.raise_for_status()
            _BooleanResponse.model_validate(created.json())
        else:
            self._configuration(response)
        for field in ("namespace", "document_id", "embedding_profile"):
            indexed = await self._client.put(
                f"{self._path}/index",
                params={"wait": "true"},
                json={"field_name": field, "field_schema": "keyword"},
            )
            indexed.raise_for_status()
            _WriteResponse.model_validate(indexed.json())

    async def ping(self) -> None:
        self._configuration(await self._client.get(self._path))

    def _embedding(self, embedding: Embedding) -> Embedding:
        if isinstance(embedding, list):
            if len(embedding) != self._dimensions or any(
                not math.isfinite(value) for value in embedding
            ):
                raise ValueError("embedding must contain the configured number of finite values")
        elif set(embedding) != {"text", "model"} or any(
            not value.strip() for value in embedding.values()
        ):
            raise ValueError("cloud inference requires text and model")
        return embedding

    def _filter(self, namespace: str, document_id: UUID | None = None) -> dict[str, object]:
        conditions: list[dict[str, object]] = [
            {"key": "namespace", "match": {"value": namespace}},
            {"key": "embedding_profile", "match": {"value": self._profile}},
        ]
        if document_id is not None:
            conditions.append({"key": "document_id", "match": {"value": str(document_id)}})
        return {"must": conditions}

    async def upsert(self, document: PreparedDocument, embeddings: list[Embedding]) -> None:
        if not document.chunks or len(document.chunks) != len(embeddings):
            raise ValueError("each document chunk requires one embedding")
        points: list[dict[str, object]] = []
        for chunk, embedding in zip(document.chunks, embeddings, strict=True):
            if chunk.namespace != document.namespace or chunk.document_id != document.id:
                raise ValueError("document chunks must belong to their document and namespace")
            point_id = uuid5(NAMESPACE_URL, f"{document.namespace}:{chunk.id}:{self._profile}")
            points.append(
                {
                    "id": str(point_id),
                    "vector": self._embedding(embedding),
                    "payload": {
                        "namespace": document.namespace,
                        "document_id": str(document.id),
                        "chunk_id": str(chunk.id),
                        "embedding_profile": self._profile,
                    },
                }
            )
        response = await self._client.put(
            f"{self._path}/points", params={"wait": "true"}, json={"points": points}
        )
        response.raise_for_status()
        _WriteResponse.model_validate(response.json())

    async def search(self, namespace: str, embedding: Embedding, limit: int) -> list[VectorHit]:
        if not 1 <= limit <= 8:
            raise ValueError("search limit must be between 1 and 8")
        response = await self._client.post(
            f"{self._path}/points/query",
            json={
                "query": self._embedding(embedding),
                "filter": self._filter(namespace),
                "limit": limit,
                "with_payload": ["namespace", "document_id", "chunk_id", "embedding_profile"],
                "with_vector": False,
            },
        )
        response.raise_for_status()
        result = _QueryResponse.model_validate(response.json())
        hits: list[VectorHit] = []
        for point in result.result.points:
            payload = point.payload
            if payload.namespace != namespace or payload.embedding_profile != self._profile:
                raise ValueError("Qdrant returned a point outside the requested embedding scope")
            hits.append(
                VectorHit(
                    chunk_id=payload.chunk_id, document_id=payload.document_id, score=point.score
                )
            )
        if len(hits) > limit:
            raise ValueError("Qdrant returned more points than the requested limit")
        return hits

    async def delete(self, namespace: str, document_id: UUID) -> None:
        response = await self._client.post(
            f"{self._path}/points/delete",
            params={"wait": "true"},
            json={"filter": self._filter(namespace, document_id)},
        )
        response.raise_for_status()
        _WriteResponse.model_validate(response.json())
