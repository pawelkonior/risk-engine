from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

import httpx
from neo4j import AsyncGraphDatabase

from app.core.settings.ai import AISettings
from app.modules.ai.contracts import KnowledgeStore, ModelProvider, VectorStore
from app.platform.ai.graph_store import Neo4jGraphStore
from app.platform.ai.providers import HTTPModelProvider
from app.platform.ai.vector_store import QdrantVectorStore


@dataclass(frozen=True)
class AIResources:
    models: ModelProvider
    vectors: VectorStore
    knowledge: KnowledgeStore


@asynccontextmanager
async def ai_resources(settings: AISettings) -> AsyncGenerator[AIResources]:
    """Use resources in one request's event loop; close every transport afterward."""
    async with AsyncExitStack() as stack:
        timeout = httpx.Timeout(settings.ai_http_timeout_seconds, connect=5)
        models_client = await stack.enter_async_context(httpx.AsyncClient(timeout=timeout))
        headers = (
            {"api-key": settings.ai_qdrant_api_key.get_secret_value()}
            if settings.ai_qdrant_api_key
            else {}
        )
        vector_client = await stack.enter_async_context(
            httpx.AsyncClient(base_url=settings.ai_qdrant_url, headers=headers, timeout=timeout)
        )
        # The upstream factory leaves its **config type unspecified.
        driver = AsyncGraphDatabase.driver(  # pyright: ignore[reportUnknownMemberType]
            settings.ai_neo4j_uri,
            auth=(settings.ai_neo4j_username, settings.ai_neo4j_password.get_secret_value()),
            connection_timeout=5,
            max_transaction_retry_time=3,
            max_connection_pool_size=4,
            notifications_min_severity="OFF",
            telemetry_disabled=True,
        )
        stack.push_async_callback(driver.close)
        yield AIResources(
            models=HTTPModelProvider(
                models_client,
                ollama_base_url=settings.ai_ollama_base_url,
                chat_provider=settings.ai_chat_provider,
                chat_model=settings.ai_chat_model,
                chat_base_url=settings.ai_chat_base_url,
                chat_api_key=settings.ai_chat_api_key,
                embedding_provider=settings.ai_embedding_provider,
                embedding_model=settings.ai_embedding_model,
                embedding_dimensions=settings.ai_embedding_dimensions,
            ),
            vectors=QdrantVectorStore(
                vector_client,
                collection=settings.ai_qdrant_collection,
                dimensions=settings.ai_embedding_dimensions,
                embedding_profile=settings.embedding_profile,
            ),
            knowledge=Neo4jGraphStore(driver, database=settings.ai_neo4j_database),
        )
