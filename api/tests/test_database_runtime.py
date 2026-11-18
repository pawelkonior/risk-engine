from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.pool import NullPool, StaticPool
from starlette.requests import Request

from app.core.config import DatabaseSettings
from app.http.dependencies import database_runtime_from_request
from app.modules.items.models import Item, UTCDateTime
from app.platform.database import DatabaseRuntime, create_database_runtime, create_engine
from app.platform.persistence import Base


@pytest.fixture
async def database() -> AsyncIterator[DatabaseRuntime]:
    runtime = DatabaseRuntime(DatabaseSettings(_env_file=None, database_url="sqlite:///:memory:"))
    async with runtime.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield runtime
    await runtime.close()


async def test_sqlite_runtime_enforces_fk_and_ping(database: DatabaseRuntime) -> None:
    assert isinstance(database.engine.pool, StaticPool)
    await database.ping()
    async with database.engine.connect() as connection:
        assert (await connection.execute(text("PRAGMA foreign_keys"))).scalar() == 1
        assert (await connection.execute(text("PRAGMA busy_timeout"))).scalar() == 5000


async def test_failed_and_uncommitted_sessions_roll_back(database: DatabaseRuntime) -> None:
    with pytest.raises(RuntimeError, match="transaction failed"):
        async with database.session() as session:
            session.add(Item(title="rolled back"))
            await session.flush()
            raise RuntimeError("transaction failed")
    async with database.session() as session:
        session.add(Item(title="not committed"))
        await session.flush()
    async with database.session() as session:
        assert not list(await session.scalars(select(Item)))


async def test_cancellation_rolls_back(database: DatabaseRuntime) -> None:
    import asyncio

    with pytest.raises(asyncio.CancelledError):
        async with database.session() as session:
            session.add(Item(title="cancelled"))
            await session.flush()
            raise asyncio.CancelledError
    async with database.session() as session:
        assert not list(await session.scalars(select(Item)))


@pytest.mark.parametrize("mode", ["queue", "null"])
async def test_postgres_engine_does_not_connect_at_creation(mode: str) -> None:
    settings = DatabaseSettings(
        _env_file=None,
        database_url="postgresql://user:secret@unreachable.invalid/application",
        database_pool_mode=mode,
    )
    runtime = create_database_runtime(settings)
    assert runtime.engine.url.drivername == "postgresql+psycopg"
    assert runtime.engine.sync_engine.hide_parameters
    if mode == "null":
        assert isinstance(runtime.engine.pool, NullPool)
    await runtime.close()


async def test_direct_migration_url_uses_nullpool(tmp_path: Path) -> None:
    settings = DatabaseSettings(
        _env_file=None,
        database_url="sqlite:///:memory:",
        database_migration_url=f"sqlite:///{tmp_path / 'migration.db'}",
    )
    engine = create_engine(settings, migrations=True)
    assert isinstance(engine.pool, NullPool)
    assert str(engine.url).endswith("migration.db")
    await engine.dispose()


async def test_nullpool_for_file_sqlite(tmp_path: Path) -> None:
    settings = DatabaseSettings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'application.db'}",
        database_pool_mode="null",
    )
    runtime = DatabaseRuntime(settings)
    assert isinstance(runtime.engine.pool, NullPool)
    await runtime.ping()
    await runtime.close()


def test_runtime_dependency_rejects_invalid_binding() -> None:
    application = FastAPI()
    application.state.database = object()
    request = Request({"type": "http", "app": application})
    with pytest.raises(RuntimeError, match="invalid"):
        database_runtime_from_request(request)


def test_utc_datetime_normalizes_database_results() -> None:
    datatype = UTCDateTime()
    now = datetime.now(UTC)
    assert datatype.process_bind_param(None, None) is None
    assert datatype.process_result_value(None, None) is None
    assert datatype.process_bind_param(now, None) == now
    assert datatype.process_result_value(now, None) == now
    assert datatype.process_result_value(now.replace(tzinfo=None), None) == now


async def test_model_constraints_and_uuid(database: DatabaseRuntime) -> None:
    from sqlalchemy.exc import IntegrityError

    async with database.session() as session:
        item = Item(id=uuid4(), title="persisted")
        session.add(item)
        await session.commit()
        await session.refresh(item)
        assert item.created_at.tzinfo is UTC
        session.add(Item(title=""))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
