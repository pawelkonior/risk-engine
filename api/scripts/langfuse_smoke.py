"""Verify AI traces in local Langfuse; retain one reusable public smoke source."""

import asyncio
import json
import os
from collections.abc import Mapping
from pathlib import Path
from time import monotonic
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, Field

from app.modules.ai.domain import DocumentStatus, QueryResponse


class Observation(BaseModel):
    name: str
    trace_id: str = Field(alias="traceId")
    observation_type: str = Field(alias="type")
    metadata: dict[str, object] = Field(default_factory=dict[str, object])
    input: object = None
    output: object = None
    model_name: str | None = Field(default=None, alias="model")


class ObservationsPage(BaseModel):
    data: list[Observation]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


async def main(local: Mapping[str, str | None]) -> None:
    def setting(name: str, fallback: str) -> str:
        return os.getenv(f"APP_{name}") or os.getenv(name) or local.get(name) or fallback

    api_url = os.getenv("AI_SMOKE_BASE_URL", "http://127.0.0.1:8080")
    langfuse_url = os.getenv(
        "LANGFUSE_SMOKE_BASE_URL", f"http://127.0.0.1:{setting('LANGFUSE_PORT', '3000')}"
    )
    capture_content = setting("LANGFUSE_CAPTURE_CONTENT", "false").lower() in {"true", "1"}
    request_id = uuid4().hex
    document_id = uuid5(NAMESPACE_URL, "template-ai:langfuse:smoke:v1")
    namespace = "langfuse_smoke"
    async with httpx.AsyncClient(base_url=api_url, timeout=60) as api:
        response = await api.put(
            f"/api/v1/ai/documents/{document_id}",
            json={
                "namespace": namespace,
                "title": "Langfuse smoke source",
                "text": (
                    "Langfuse provides AI observability. LangGraph executes the retrieval workflow."
                ),
            },
        )
        response.raise_for_status()
        require(
            DocumentStatus.model_validate(response.json()).status == "ready",
            "The smoke source must finish indexing",
        )
        response = await api.post(
            "/api/v1/ai/query",
            headers={"X-Request-ID": request_id},
            json={"namespace": namespace, "question": "What does Langfuse provide?"},
        )
        response.raise_for_status()
        answer = QueryResponse.model_validate(response.json())
        require(bool(answer.sources), "The query must retrieve its source and run generation")

    expected = {"ai.query", "ai.embed", "ai.retrieve", "ai.graph", "ai.generate"}
    filters = [
        {
            "type": "stringObject",
            "column": "metadata",
            "key": "request_id",
            "operator": "=",
            "value": request_id,
        }
    ]
    async with httpx.AsyncClient(
        base_url=langfuse_url,
        auth=httpx.BasicAuth(
            setting("LANGFUSE_PUBLIC_KEY", "pk-lf-template-local"),
            setting("LANGFUSE_SECRET_KEY", "sk-lf-template-local"),
        ),
        timeout=5,
    ) as langfuse:
        deadline = monotonic() + 45
        observations: list[Observation] = []
        while monotonic() < deadline:
            response = await langfuse.get(
                "/api/public/v2/observations",
                params={
                    "fields": "core,basic,io,metadata,model",
                    "limit": 100,
                    "filter": json.dumps(filters),
                },
            )
            response.raise_for_status()
            observations = ObservationsPage.model_validate(response.json()).data
            if expected <= {observation.name for observation in observations}:
                break
            await asyncio.sleep(1)
        require(
            expected <= {observation.name for observation in observations},
            "Langfuse did not persist the complete query trace before the deadline",
        )
        require(
            len({observation.trace_id for observation in observations}) == 1,
            "The query stages must share one trace",
        )
        require(
            any(
                observation.observation_type == "GENERATION" and observation.model_name
                for observation in observations
            ),
            "Langfuse must recognize the generation and model",
        )
        if not capture_content:
            require(
                all(
                    observation.input is None and observation.output is None
                    for observation in observations
                ),
                "Content must remain absent when capture is disabled",
            )
    print(
        json.dumps(
            {
                "status": "passed",
                "observations": len(observations),
                "trace_id": observations[0].trace_id,
                "request_id": request_id,
                "capture_content": capture_content,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main(dotenv_values(Path(__file__).resolve().parents[2] / ".env")))
