"""Explicit, request-scoped Langfuse observations over public OTLP HTTP/JSON."""

import asyncio
import json
import logging
import math
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import time_ns
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field

from app.core.context import get_request_id
from app.core.settings.langfuse import LangfuseSettings
from app.modules.ai.contracts import (
    AIObservation,
    NoopAIObserver,
    ObservationKind,
    TraceMetadata,
)

_logger = logging.getLogger(__name__)
_MAX_SPANS = 64
_MAX_CONTENT_CHARACTERS = 16_384
_METADATA_KEYS = frozenset(
    {
        "request_id",
        "namespace",
        "document_id",
        "collection",
        "embedding_profile",
        "limit",
        "hit_count",
        "ready_count",
        "chunk_count",
        "fact_count",
        "source_count",
        "status",
        "idempotent",
        "question_characters",
        "input_characters",
        "output_characters",
        "embedding_count",
    }
)


class _PartialSuccess(BaseModel):
    rejected_spans: int = Field(default=0, alias="rejectedSpans", ge=0, le=2**63 - 1)


class _ExportResponse(BaseModel):
    partial_success: _PartialSuccess | None = Field(default=None, alias="partialSuccess")


def _metadata(values: TraceMetadata | None) -> dict[str, str | int | float | bool]:
    return {
        key: value[:256] if isinstance(value, str) else value
        for key, value in (values or {}).items()
        if key in _METADATA_KEYS and (not isinstance(value, float) or math.isfinite(value))
    }


def _attribute(key: str, value: str | int | float | bool) -> dict[str, object]:
    if isinstance(value, bool):
        encoded = {"boolValue": value}
    elif isinstance(value, int):
        encoded = {"intValue": str(value)}
    elif isinstance(value, float):
        encoded = {"doubleValue": value}
    else:
        encoded = {"stringValue": value}
    return {"key": key, "value": encoded}


@dataclass(frozen=True)
class _Parent:
    trace_id: str
    span_id: str
    metadata: TraceMetadata


class _Observation:
    def __init__(
        self,
        name: str,
        kind: ObservationKind,
        trace_id: str,
        parent_id: str | None,
        metadata: TraceMetadata,
        capture_content: bool,
        model: str | None,
    ) -> None:
        self.name = name
        self.kind = kind
        self.trace_id = trace_id
        self.parent_id = parent_id
        self.span_id = uuid4().hex[:16]
        self.started = time_ns()
        self.metadata = dict(metadata)
        self.capture_content = capture_content
        self.model = model
        self.input: str | None = None
        self.output: str | None = None
        self.error_type: str | None = None

    def _content(self, value: object) -> str | None:
        if not self.capture_content or value is None:
            return None
        try:
            serialized = json.dumps(value, ensure_ascii=True, allow_nan=False)
        except TypeError, ValueError, RecursionError:
            return None
        if len(serialized) > _MAX_CONTENT_CHARACTERS:
            serialized = json.dumps(
                {"truncated": True, "preview": serialized[: (_MAX_CONTENT_CHARACTERS - 128) // 2]},
                ensure_ascii=True,
            )
        return serialized

    def update(
        self, *, metadata: TraceMetadata | None = None, input: object = None, output: object = None
    ) -> None:
        self.metadata.update(_metadata(metadata))
        if input is not None:
            self.input = self._content(input)
        if output is not None:
            self.output = self._content(output)

    def export(self) -> dict[str, object]:
        attributes = [_attribute("langfuse.observation.type", self.kind)]
        attributes.extend(
            _attribute(f"langfuse.observation.metadata.{key}", value)
            for key, value in self.metadata.items()
        )
        if self.model is not None:
            attributes.append(_attribute("langfuse.observation.model.name", self.model))
        if self.input is not None:
            attributes.append(_attribute("langfuse.observation.input", self.input))
        if self.output is not None:
            attributes.append(_attribute("langfuse.observation.output", self.output))
        if self.error_type is not None:
            attributes.extend(
                [
                    _attribute("langfuse.observation.level", "ERROR"),
                    _attribute("error.type", self.error_type),
                ]
            )
        span: dict[str, object] = {
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "name": self.name,
            "kind": 1,
            "startTimeUnixNano": str(self.started),
            "endTimeUnixNano": str(max(self.started, time_ns())),
            "attributes": attributes,
            "status": {"code": 2 if self.error_type is not None else 1},
        }
        if self.parent_id is not None:
            span["parentSpanId"] = self.parent_id
        return span


class LangfuseObserver:
    """Buffer one request's spans and export once without global instrumentation."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        capture_content: bool = False,
        timeout_seconds: float = 3,
        chat_model: str | None = None,
        embedding_model: str | None = None,
    ) -> None:
        self._client = client
        self._capture_content = capture_content
        self._timeout_seconds = timeout_seconds
        self._chat_model = chat_model
        self._embedding_model = embedding_model
        self._parent: ContextVar[_Parent | None] = ContextVar("langfuse_observation", default=None)
        self._spans: list[dict[str, object]] = []
        self._reserved = 0

    @contextmanager
    def span(
        self,
        name: str,
        *,
        kind: ObservationKind = "span",
        metadata: TraceMetadata | None = None,
        input: object = None,
    ) -> Generator[AIObservation]:
        if self._client is None or self._reserved >= _MAX_SPANS:
            yield NoopAIObserver()
            return
        self._reserved += 1
        parent = self._parent.get()
        inherited = dict(parent.metadata) if parent is not None else {}
        request_id = get_request_id()
        if request_id is not None:
            inherited["request_id"] = request_id
        inherited.update(_metadata(metadata))
        observation = _Observation(
            name=name,
            kind=kind,
            trace_id=parent.trace_id if parent is not None else uuid4().hex,
            parent_id=parent.span_id if parent is not None else None,
            metadata=inherited,
            capture_content=self._capture_content,
            model=self._chat_model
            if kind == "generation"
            else (self._embedding_model if kind == "embedding" else None),
        )
        observation.update(input=input)
        token = self._parent.set(_Parent(observation.trace_id, observation.span_id, inherited))
        try:
            yield observation
        except BaseException as error:
            observation.error_type = type(error).__name__
            raise
        finally:
            self._parent.reset(token)
            self._spans.append(observation.export())

    async def flush(self) -> None:
        if self._client is None or not self._spans:
            return
        spans, self._spans = self._spans, []
        self._reserved = 0
        payload = {
            "resourceSpans": [
                {
                    "resource": {"attributes": [_attribute("service.name", "application-api")]},
                    "scopeSpans": [{"scope": {"name": "application.ai"}, "spans": spans}],
                }
            ]
        }
        try:
            async with asyncio.timeout(self._timeout_seconds):
                response = await self._client.post("/api/public/otel/v1/traces", json=payload)
                response.raise_for_status()
                if response.content:
                    result = _ExportResponse.model_validate_json(response.content)
                    if result.partial_success is not None and result.partial_success.rejected_spans:
                        _logger.warning(
                            "Langfuse trace export rejected spans",
                            extra={"rejected_span_count": result.partial_success.rejected_spans},
                        )
        except Exception:
            _logger.warning("Langfuse trace export failed")


@asynccontextmanager
async def langfuse_observer(
    settings: LangfuseSettings,
    *,
    chat_model: str | None = None,
    embedding_model: str | None = None,
) -> AsyncGenerator[LangfuseObserver]:
    if not settings.langfuse_enabled:
        yield LangfuseObserver()
        return
    # Validation ensures credentials are present whenever export is enabled.
    if settings.langfuse_public_key is None or settings.langfuse_secret_key is None:
        raise ValueError("Langfuse credentials are required")
    async with httpx.AsyncClient(
        base_url=settings.langfuse_base_url,
        auth=httpx.BasicAuth(
            settings.langfuse_public_key.get_secret_value(),
            settings.langfuse_secret_key.get_secret_value(),
        ),
        headers={"x-langfuse-ingestion-version": "4"},
        timeout=httpx.Timeout(settings.langfuse_timeout_seconds, connect=1),
        follow_redirects=False,
    ) as client:
        observer = LangfuseObserver(
            client,
            capture_content=settings.langfuse_capture_content,
            timeout_seconds=settings.langfuse_timeout_seconds,
            chat_model=chat_model,
            embedding_model=embedding_model,
        )
        try:
            yield observer
        finally:
            await observer.flush()
