import asyncio
from collections.abc import AsyncGenerator, Awaitable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.core.errors import DependencyUnavailableError
from app.http.dependencies import DatabaseSession, SettingsDependency
from app.modules.ai.domain import (
    DocumentInput,
    DocumentStatus,
    Namespace,
    QueryInput,
    QueryResponse,
)
from app.modules.ai.service import AiService
from app.platform.ai.observability import langfuse_observer
from app.platform.ai.runtime import AIResources, ai_resources

router = APIRouter(prefix="/ai", tags=["ai"])


class AIStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    chat_provider: str
    chat_model: str
    embedding_provider: str
    embedding_model: str
    collection: str


async def resources_from_settings(settings: SettingsDependency) -> AsyncGenerator[AIResources]:
    if not settings.ai.ai_enabled:
        raise DependencyUnavailableError("AI is disabled for this application")
    async with ai_resources(settings.ai) as resources:
        yield resources


ResourcesDependency = Annotated[AIResources, Depends(resources_from_settings)]


async def service(
    session: DatabaseSession, settings: SettingsDependency, resources: ResourcesDependency
) -> AsyncGenerator[AiService]:
    async with langfuse_observer(
        settings.langfuse,
        chat_model=settings.ai.ai_chat_model,
        embedding_model=settings.ai.ai_embedding_model,
    ) as observer:
        yield AiService(
            session,
            resources.models,
            resources.vectors,
            resources.knowledge,
            collection=settings.ai.ai_qdrant_collection,
            embedding_profile=settings.ai.embedding_profile,
            observer=observer,
        )


ServiceDependency = Annotated[AiService, Depends(service, scope="function")]


async def bounded[T](operation: Awaitable[T], deadline_seconds: float) -> T:
    try:
        async with asyncio.timeout(deadline_seconds):
            return await operation
    except TimeoutError:
        raise DependencyUnavailableError("AI request exceeded the time limit") from None


@router.get("/status", response_model=AIStatus)
async def status(settings: SettingsDependency) -> AIStatus:
    """Expose configuration identity without credentials or connection attempts."""
    ai = settings.ai
    return AIStatus(
        enabled=ai.ai_enabled,
        chat_provider=ai.ai_chat_provider,
        chat_model=ai.ai_chat_model,
        embedding_provider=ai.ai_embedding_provider,
        embedding_model=ai.ai_embedding_model,
        collection=ai.ai_qdrant_collection,
    )


@router.put("/documents/{document_id}", response_model=DocumentStatus)
async def ingest(
    document_id: UUID,
    payload: DocumentInput,
    ai: ServiceDependency,
    settings: SettingsDependency,
) -> DocumentStatus:
    """Index an immutable source; repeating the same request is safe."""
    return await bounded(ai.ingest(document_id, payload), settings.ai.ai_request_timeout_seconds)


@router.get("/documents/{document_id}", response_model=DocumentStatus)
async def document_status(
    document_id: UUID,
    ai: ServiceDependency,
    settings: SettingsDependency,
    namespace: Namespace = "default",
) -> DocumentStatus:
    return await bounded(ai.status(document_id, namespace), settings.ai.ai_request_timeout_seconds)


@router.post("/query", response_model=QueryResponse)
async def query(
    payload: QueryInput, ai: ServiceDependency, settings: SettingsDependency
) -> QueryResponse:
    """Run a bounded, stateless LangGraph query against indexed sources."""
    return await bounded(ai.query(payload), settings.ai.ai_request_timeout_seconds)
