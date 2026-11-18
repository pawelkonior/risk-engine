from collections.abc import Mapping
from contextlib import AbstractContextManager, nullcontext
from typing import Literal, Protocol
from uuid import UUID

from app.modules.ai.domain import GraphContext, PreparedDocument, VectorHit

Vector = list[float]
Embedding = Vector | dict[str, str]
TraceMetadata = Mapping[str, str | int | float | bool]
ObservationKind = Literal["span", "generation", "embedding", "retriever"]


class AIObservation(Protocol):
    def update(
        self, *, metadata: TraceMetadata | None = None, input: object = None, output: object = None
    ) -> None: ...


class AIObserver(Protocol):
    def span(
        self,
        name: str,
        *,
        kind: ObservationKind = "span",
        metadata: TraceMetadata | None = None,
        input: object = None,
    ) -> AbstractContextManager[AIObservation]: ...


class NoopAIObserver:
    """Keep application instrumentation inert when observability is disabled."""

    def span(
        self,
        name: str,
        *,
        kind: ObservationKind = "span",
        metadata: TraceMetadata | None = None,
        input: object = None,
    ) -> AbstractContextManager[AIObservation]:
        return nullcontext(self)

    def update(
        self, *, metadata: TraceMetadata | None = None, input: object = None, output: object = None
    ) -> None:
        pass


class ModelProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[Embedding]: ...

    async def generate(self, system: str, question: str) -> str: ...


class VectorStore(Protocol):
    async def setup(self) -> None: ...

    async def ping(self) -> None: ...

    async def upsert(self, document: PreparedDocument, embeddings: list[Embedding]) -> None: ...

    async def search(self, namespace: str, embedding: Embedding, limit: int) -> list[VectorHit]: ...

    async def delete(self, namespace: str, document_id: UUID) -> None: ...


class KnowledgeStore(Protocol):
    async def setup(self) -> None: ...

    async def ping(self) -> None: ...

    async def upsert(self, document: PreparedDocument) -> None: ...

    async def context(self, namespace: str, chunk_ids: list[UUID]) -> GraphContext: ...

    async def delete(self, namespace: str, document_id: UUID) -> None: ...
