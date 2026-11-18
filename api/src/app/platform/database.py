from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

from app.core.config import DatabaseSettings


def create_engine(settings: DatabaseSettings, *, migrations: bool = False) -> AsyncEngine:
    """Build an engine without opening connections, including serverless-safe options."""
    url = make_url(
        settings.migration_url if migrations else settings.database_url.get_secret_value()
    )
    options: dict[str, Any] = {"hide_parameters": True}
    if url.get_backend_name() == "sqlite":
        options["connect_args"] = {"timeout": settings.database_connect_timeout_seconds}
        if url.database == ":memory:":
            options["poolclass"] = StaticPool
        elif migrations or settings.database_pool_mode == "null":
            options["poolclass"] = NullPool
    else:
        options["connect_args"] = {
            "connect_timeout": settings.database_connect_timeout_seconds,
            "prepare_threshold": None,
        }
        if migrations or settings.database_pool_mode == "null":
            options["poolclass"] = NullPool
        else:
            options.update(
                pool_pre_ping=True,
                pool_size=settings.database_pool_size,
                max_overflow=settings.database_max_overflow,
                pool_timeout=settings.database_pool_timeout_seconds,
            )
    engine = create_async_engine(url, **options)
    if url.get_backend_name() == "sqlite":
        event.listen(engine.sync_engine, "connect", _configure_sqlite)
    return engine


def _configure_sqlite(dbapi_connection: Any, _connection_record: Any) -> None:
    """Enable SQLite integrity checks for every connection, including migrations."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


class DatabaseRuntime:
    """Own one lazy engine and request-scoped session factory."""

    def __init__(self, settings: DatabaseSettings) -> None:
        self.engine = create_engine(settings)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine, expire_on_commit=False, autoflush=False
        )

    async def ping(self) -> None:
        """Check connectivity without requiring an application table."""
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession]:
        """Never commit implicitly; close and roll back after errors or cancellation."""
        async with self._session_factory() as session:
            try:
                yield session
            except BaseException:
                await session.rollback()
                raise

    async def close(self) -> None:
        """Release idle database connections."""
        await self.engine.dispose()


def create_database_runtime(settings: DatabaseSettings) -> DatabaseRuntime:
    return DatabaseRuntime(settings)
