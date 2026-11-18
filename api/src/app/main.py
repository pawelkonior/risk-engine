import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.http.exception_handlers import register_exception_handlers
from app.http.middleware import register_middleware
from app.http.openapi import stable_operation_id
from app.http.router import root_router
from app.platform.database import DatabaseRuntime, create_database_runtime

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
    """Release process resources without migrations or network calls at startup."""
    database: DatabaseRuntime = application.state.database
    logger.info("Application started")
    try:
        yield
    finally:
        await database.close()
        logger.info("Application stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Assemble a usable ASGI app even when a host does not drive lifespan."""
    resolved = settings or get_settings()
    configure_logging(resolved.runtime.log_level)
    docs_enabled = resolved.http.docs_enabled
    application = FastAPI(
        # FastAPI's native telemetry remains disabled even when host OTEL variables exist.
        telemetry={
            "tracing": False,
            "metrics": False,
            "logs": False,
            "operation_spans": False,
            "auto_configure": False,
        },
        title=resolved.runtime.name,
        version=resolved.runtime.version,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        generate_unique_id_function=stable_operation_id,
    )
    application.state.settings = resolved
    application.state.database = create_database_runtime(resolved.database)
    register_middleware(application, resolved.http)
    register_exception_handlers(application)
    application.include_router(root_router)
    return application


app = create_app()
