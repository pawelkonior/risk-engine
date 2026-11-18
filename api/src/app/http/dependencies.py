from collections.abc import AsyncGenerator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.platform.database import DatabaseRuntime


def settings_from_request(request: Request) -> Settings:
    """Return the validated settings bound to the current application."""
    return cast(Settings, request.app.state.settings)


def database_runtime_from_request(request: Request) -> DatabaseRuntime:
    """Return the required database runtime bound to this application."""
    runtime = request.app.state.database
    if not isinstance(runtime, DatabaseRuntime):
        raise RuntimeError("application database runtime is invalid")
    return runtime


async def database_session(request: Request) -> AsyncGenerator[AsyncSession]:
    """Provide a separate session for each request; services own their commits."""
    async with database_runtime_from_request(request).session() as session:
        yield session


SettingsDependency = Annotated[Settings, Depends(settings_from_request)]
DatabaseRuntimeDependency = Annotated[DatabaseRuntime, Depends(database_runtime_from_request)]
DatabaseSession = Annotated[AsyncSession, Depends(database_session)]
