import hashlib
import json
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import ConflictError, DependencyUnavailableError, NotFoundError
from app.modules.ai.contracts import (
    AIObservation,
    AIObserver,
    KnowledgeStore,
    ModelProvider,
    NoopAIObserver,
    VectorStore,
)
from app.modules.ai.domain import (
    Chunk,
    DocumentInput,
    DocumentStatus,
    PreparedDocument,
    QueryInput,
    QueryResponse,
    StoredFact,
)
from app.modules.ai.models import AIIndexRecord
from app.modules.ai.workflow import QueryWorkflow, tracing_disabled

_CHUNK_SIZE = 1_000
_CHUNK_OVERLAP = 200


def _stable_id(*parts: str) -> UUID:
    return uuid5(NAMESPACE_URL, json.dumps(parts, ensure_ascii=False, separators=(",", ":")))


def prepare_document(document_id: UUID, payload: DocumentInput) -> PreparedDocument:
    """Prepare immutable IDs and exact source evidence without model-generated facts."""
    canonical = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    content_hash = hashlib.sha256(canonical.encode()).hexdigest()
    chunks: list[Chunk] = []
    for position, start in enumerate(range(0, len(payload.text), _CHUNK_SIZE - _CHUNK_OVERLAP)):
        chunks.append(
            Chunk(
                id=_stable_id(payload.namespace, str(document_id), content_hash, str(position)),
                document_id=document_id,
                namespace=payload.namespace,
                title=payload.title,
                text=payload.text[start : start + _CHUNK_SIZE],
                position=position,
            )
        )
        if start + _CHUNK_SIZE >= len(payload.text):
            break
    facts: list[StoredFact] = []
    for fact in payload.facts:
        chunk = next(chunk for chunk in chunks if fact.evidence in chunk.text)
        subject_kind = fact.subject.kind.strip().casefold()
        object_kind = fact.object.kind.strip().casefold()
        subject = fact.subject.name.strip()
        object_name = fact.object.name.strip()
        predicate = fact.predicate.strip()
        subject_id = _stable_id(payload.namespace, subject_kind, subject.casefold())
        object_id = _stable_id(payload.namespace, object_kind, object_name.casefold())
        facts.append(
            StoredFact(
                id=_stable_id(
                    str(document_id),
                    str(subject_id),
                    predicate.casefold(),
                    str(object_id),
                    fact.evidence,
                ),
                subject_id=subject_id,
                subject=subject,
                subject_kind=subject_kind,
                predicate=predicate,
                object_id=object_id,
                object=object_name,
                object_kind=object_kind,
                evidence=fact.evidence,
                chunk_id=chunk.id,
                document_id=document_id,
                namespace=payload.namespace,
            )
        )
    return PreparedDocument(
        id=document_id,
        namespace=payload.namespace,
        title=payload.title,
        content_hash=content_hash,
        chunks=chunks,
        facts=facts,
    )


class AiService:
    """Coordinate recoverable indexing and expose only fully indexed documents."""

    def __init__(
        self,
        session: AsyncSession,
        models: ModelProvider,
        vectors: VectorStore,
        knowledge: KnowledgeStore,
        collection: str,
        embedding_profile: str,
        *,
        observer: AIObserver | None = None,
    ) -> None:
        self.session = session
        self.models = models
        self.vectors = vectors
        self.knowledge = knowledge
        self.collection = collection
        self.embedding_profile = embedding_profile
        self.observer = observer if observer is not None else NoopAIObserver()

    def _conditions(self, document_id: UUID, namespace: str) -> tuple[ColumnElement[bool], ...]:
        return (
            AIIndexRecord.document_id == document_id,
            AIIndexRecord.namespace == namespace,
            AIIndexRecord.collection == self.collection,
        )

    async def _record(self, document_id: UUID, namespace: str) -> AIIndexRecord | None:
        return await self.session.scalar(
            select(AIIndexRecord)
            .where(*self._conditions(document_id, namespace))
            .execution_options(populate_existing=True)
        )

    @staticmethod
    def _status(record: AIIndexRecord) -> DocumentStatus:
        return DocumentStatus(
            document_id=record.document_id,
            namespace=record.namespace,
            status=record.status,
            chunk_count=record.chunk_count,
            collection=record.collection,
        )

    async def status(self, document_id: UUID, namespace: str) -> DocumentStatus:
        record = await self._record(document_id, namespace)
        if record is None:
            raise NotFoundError("Document was not found")
        return self._status(record)

    def _check_identity(self, record: AIIndexRecord, document: PreparedDocument) -> None:
        if record.content_hash != document.content_hash:
            raise ConflictError("Document IDs are immutable; use a new ID for different content")
        if record.embedding_profile != self.embedding_profile:
            raise ConflictError("The document uses a different embedding profile")

    async def _reserve(self, document: PreparedDocument) -> DocumentStatus | None:
        record = await self._record(document.id, document.namespace)
        if record is None:
            record = AIIndexRecord(
                document_id=document.id,
                namespace=document.namespace,
                collection=self.collection,
                content_hash=document.content_hash,
                embedding_profile=self.embedding_profile,
                status="pending",
                chunk_count=len(document.chunks),
                error_code=None,
            )
            self.session.add(record)
            try:
                await self.session.commit()
            except IntegrityError:
                await self.session.rollback()
                record = await self._record(document.id, document.namespace)
                if record is None:
                    raise
            else:
                return None
        self._check_identity(record, document)
        if record.status == "ready":
            status = self._status(record)
            await self.session.commit()
            return status
        await self.session.execute(
            update(AIIndexRecord)
            .where(
                *self._conditions(document.id, document.namespace), AIIndexRecord.status != "ready"
            )
            .values(status="pending", error_code=None)
        )
        await self.session.commit()
        return None

    async def _finish(self, document: PreparedDocument, status: str) -> None:
        statement = update(AIIndexRecord).where(*self._conditions(document.id, document.namespace))
        if status == "failed":
            statement = statement.where(AIIndexRecord.status != "ready")
        await self.session.execute(
            statement.values(
                status=status, error_code="indexing_failed" if status == "failed" else None
            )
        )
        await self.session.commit()

    async def ingest(self, document_id: UUID, payload: DocumentInput) -> DocumentStatus:
        with self.observer.span(
            "ai.ingest",
            metadata={
                "document_id": str(document_id),
                "namespace": payload.namespace,
                "collection": self.collection,
                "embedding_profile": self.embedding_profile,
                "input_characters": len(payload.text),
            },
            input=payload.model_dump(mode="json"),
        ) as observation:
            result = await self._ingest(document_id, payload, observation)
            observation.update(
                metadata={"status": result.status, "chunk_count": result.chunk_count},
                output=result.model_dump(mode="json"),
            )
            return result

    async def _ingest(
        self, document_id: UUID, payload: DocumentInput, observation: AIObservation
    ) -> DocumentStatus:
        document = prepare_document(document_id, payload)
        completed = await self._reserve(document)
        observation.update(
            metadata={
                "idempotent": completed is not None,
                "chunk_count": len(document.chunks),
                "fact_count": len(document.facts),
            }
        )
        if completed is not None:
            return completed
        try:
            with tracing_disabled():
                texts = [chunk.text for chunk in document.chunks]
                with self.observer.span("ai.embed", kind="embedding", input=texts) as observation:
                    embeddings = await self.models.embed(texts)
                    if len(embeddings) != len(document.chunks):
                        raise ValueError("The embedding provider returned an invalid batch")
                    observation.update(metadata={"embedding_count": len(embeddings)})
                with self.observer.span("ai.vector.upsert"):
                    await self.vectors.upsert(document, embeddings)
                with self.observer.span("ai.graph.upsert"):
                    await self.knowledge.upsert(document)
            await self._finish(document, "ready")
        except Exception:
            await self.session.rollback()
            await self._finish(document, "failed")
            raise DependencyUnavailableError() from None
        return DocumentStatus(
            document_id=document.id,
            namespace=document.namespace,
            status="ready",
            chunk_count=len(document.chunks),
            collection=self.collection,
        )

    async def _ready_documents(self, namespace: str, document_ids: list[UUID]) -> set[UUID]:
        if not document_ids:
            return set()
        result = await self.session.scalars(
            select(AIIndexRecord.document_id).where(
                AIIndexRecord.namespace == namespace,
                AIIndexRecord.collection == self.collection,
                AIIndexRecord.embedding_profile == self.embedding_profile,
                AIIndexRecord.status == "ready",
                AIIndexRecord.document_id.in_(document_ids),
            )
        )
        ready = set(result)
        await self.session.commit()
        return ready

    async def query(self, payload: QueryInput) -> QueryResponse:
        with self.observer.span(
            "ai.query",
            metadata={
                "namespace": payload.namespace,
                "collection": self.collection,
                "embedding_profile": self.embedding_profile,
                "limit": payload.limit,
                "question_characters": len(payload.question),
            },
            input=payload.model_dump(mode="json"),
        ) as observation:
            try:
                result = await QueryWorkflow(
                    self.models,
                    self.vectors,
                    self.knowledge,
                    self._ready_documents,
                    observer=self.observer,
                ).run(payload)
                observation.update(
                    metadata={
                        "source_count": len(result.sources),
                        "fact_count": len(result.facts),
                        "output_characters": len(result.answer),
                    },
                    output=result.model_dump(mode="json"),
                )
                return result
            except Exception:
                raise DependencyUnavailableError() from None
