import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.errors import ConflictError, DependencyUnavailableError, NotFoundError
from app.modules.ai.contracts import KnowledgeStore, ModelProvider, VectorStore
from app.modules.ai.domain import (
    DocumentInput,
    EntityInput,
    FactInput,
    GraphContext,
    QueryInput,
    VectorHit,
)
from app.modules.ai.models import AIIndexRecord
from app.modules.ai.service import AiService, prepare_document
from app.platform.persistence import Base


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def providers() -> tuple[Mock, Mock, Mock]:
    models = Mock(spec=ModelProvider)
    models.embed = AsyncMock(side_effect=embed)
    models.generate = AsyncMock(return_value="Odpowiedź [S1]")
    vectors = Mock(spec=VectorStore)
    vectors.upsert = AsyncMock()
    vectors.search = AsyncMock(return_value=[])
    knowledge = Mock(spec=KnowledgeStore)
    knowledge.upsert = AsyncMock()
    knowledge.context = AsyncMock(return_value=GraphContext())
    return models, vectors, knowledge


def embed(texts: list[str]) -> list[list[float]]:
    return [[1.0] for _ in texts]


def payload() -> DocumentInput:
    return DocumentInput(
        title="Polska",
        text="Warszawa jest stolicą Polski.",
        facts=[
            FactInput(
                subject=EntityInput(name="Warszawa", kind="city"),
                predicate="capital_of",
                object=EntityInput(name="Polska", kind="country"),
                evidence="Warszawa jest stolicą Polski.",
            )
        ],
    )


def test_preparation_is_deterministic_and_preserves_boundary_evidence() -> None:
    document_id = uuid4()
    document = payload()
    evidence = "Warszawa jest stolicą Polski."
    document.text = "a" * 990 + evidence + "b" * 1_100
    first = prepare_document(document_id, document)
    assert first == prepare_document(document_id, document)
    assert len(first.chunks) == 3
    assert first.chunks[0].text[-10:] == evidence[:10]
    assert first.facts[0].evidence in first.chunks[1].text
    assert first.facts[0].chunk_id == first.chunks[1].id
    other_namespace = prepare_document(
        document_id, document.model_copy(update={"namespace": "other"})
    )
    assert first.facts[0].subject_id != other_namespace.facts[0].subject_id
    assert first.chunks[0].id != other_namespace.chunks[0].id


async def test_ingestion_is_ordered_idempotent_and_immutable(session: AsyncSession) -> None:
    models, vectors, knowledge = providers()
    calls: list[str] = []

    async def vector_upsert(*_args: object) -> None:
        record = await session.scalar(select(AIIndexRecord))
        assert record is not None and record.status == "pending"
        calls.append("vector")

    async def graph_upsert(*_args: object) -> None:
        calls.append("graph")

    vectors.upsert.side_effect = vector_upsert
    knowledge.upsert.side_effect = graph_upsert
    service = AiService(session, models, vectors, knowledge, "test", "ollama:model")
    document_id = uuid4()
    result = await service.ingest(document_id, payload())
    assert result.status == "ready" and result.chunk_count == 1
    assert calls == ["vector", "graph"]
    assert await service.ingest(document_id, payload()) == result
    models.embed.assert_awaited_once()
    assert await service.status(document_id, "default") == result
    with pytest.raises(ConflictError, match="immutable"):
        await service.ingest(document_id, payload().model_copy(update={"title": "Changed"}))
    with pytest.raises(ConflictError, match="embedding profile"):
        await AiService(session, models, vectors, knowledge, "test", "other").ingest(
            document_id, payload()
        )
    with pytest.raises(NotFoundError):
        await service.status(document_id, "other")


@pytest.mark.parametrize("failing_store", ["vectors", "knowledge", "embedding_batch"])
async def test_failed_ingestion_can_retry_without_exposing_orphan_vectors(
    session: AsyncSession, failing_store: str
) -> None:
    models, vectors, knowledge = providers()
    if failing_store == "embedding_batch":
        models.embed.side_effect = None
        models.embed.return_value = []
    else:
        (vectors if failing_store == "vectors" else knowledge).upsert.side_effect = RuntimeError(
            "secret provider credentials"
        )
    service = AiService(session, models, vectors, knowledge, "test", "local")
    document_id = uuid4()
    with pytest.raises(DependencyUnavailableError) as error:
        await service.ingest(document_id, payload())
    assert "secret" not in str(error.value)
    assert (await service.status(document_id, "default")).status == "failed"
    record = await session.scalar(select(AIIndexRecord))
    assert record is not None and record.error_code == "indexing_failed"
    prepared = prepare_document(document_id, payload())
    vectors.search.return_value = [
        VectorHit(chunk_id=prepared.chunks[0].id, document_id=document_id, score=1)
    ]
    models.embed.side_effect = embed
    response = await service.query(QueryInput(question="Q"))
    assert response.sources == []
    knowledge.context.assert_not_awaited()
    vectors.upsert.side_effect = knowledge.upsert.side_effect = None
    assert (await service.ingest(document_id, payload())).status == "ready"


async def test_ready_state_wins_over_a_concurrent_failed_attempt(session: AsyncSession) -> None:
    models, vectors, knowledge = providers()

    async def concurrent_success(*_args: object) -> None:
        await session.execute(update(AIIndexRecord).values(status="ready"))
        await session.commit()
        raise RuntimeError("A concurrent identical attempt succeeded")

    knowledge.upsert.side_effect = concurrent_success
    service = AiService(session, models, vectors, knowledge, "test", "local")
    document_id = uuid4()
    with pytest.raises(DependencyUnavailableError):
        await service.ingest(document_id, payload())
    assert (await service.status(document_id, "default")).status == "ready"


async def test_cancelled_ingestion_stays_pending_and_can_resume(session: AsyncSession) -> None:
    models, vectors, knowledge = providers()
    knowledge.upsert.side_effect = asyncio.CancelledError()
    service = AiService(session, models, vectors, knowledge, "test", "local")
    document_id = uuid4()
    with pytest.raises(asyncio.CancelledError):
        await service.ingest(document_id, payload())
    assert (await service.status(document_id, "default")).status == "pending"
    knowledge.upsert.side_effect = None
    assert (await service.ingest(document_id, payload())).status == "ready"


async def test_simultaneous_first_ingestions_recover_the_unique_key_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    document_id = uuid4()
    barrier = asyncio.Event()
    arrivals = 0
    models, vectors, knowledge = providers()
    async with factory() as first_session, factory() as second_session:
        services = [
            AiService(current, models, vectors, knowledge, "test", "local")
            for current in (first_session, second_session)
        ]

        def synchronize_initial_read(service: AiService) -> None:
            # Pause between lookup and insertion to force the real unique-key race.
            original = service._record  # pyright: ignore[reportPrivateUsage]
            first_read = True

            async def read(document_id: UUID, namespace: str) -> AIIndexRecord | None:
                nonlocal first_read, arrivals
                record = await original(document_id, namespace)
                if first_read:
                    first_read = False
                    assert record is None
                    await service.session.rollback()
                    arrivals += 1
                    if arrivals == 2:
                        barrier.set()
                    await barrier.wait()
                return record

            monkeypatch.setattr(service, "_record", read)

        for service in services:
            synchronize_initial_read(service)
        results = await asyncio.gather(
            *(service.ingest(document_id, payload()) for service in services)
        )
        assert all(result.status == "ready" for result in results)
        rows = list(await first_session.scalars(select(AIIndexRecord)))
        assert len(rows) == 1 and rows[0].status == "ready"
    await engine.dispose()


async def test_query_only_expands_ready_documents_for_the_same_collection_and_profile(
    session: AsyncSession,
) -> None:
    models, vectors, knowledge = providers()
    document_id = uuid4()
    service = AiService(session, models, vectors, knowledge, "test", "local")
    await service.ingest(document_id, payload())
    prepared = prepare_document(document_id, payload())
    vectors.search.return_value = [
        VectorHit(chunk_id=prepared.chunks[0].id, document_id=document_id, score=1)
    ]
    knowledge.context.return_value = GraphContext(chunks=prepared.chunks, facts=prepared.facts)
    response = await service.query(QueryInput(question="Co jest stolicą Polski?"))
    assert response.answer == "Odpowiedź [S1]"
    assert response.sources[0].document_id == document_id
    for collection, profile in [("other", "local"), ("test", "different")]:
        isolated = await AiService(session, models, vectors, knowledge, collection, profile).query(
            QueryInput(question="Q")
        )
        assert isolated.sources == []
    vectors.search.side_effect = RuntimeError("secret")
    with pytest.raises(DependencyUnavailableError, match="temporarily unavailable"):
        await service.query(QueryInput(question="Q"))
