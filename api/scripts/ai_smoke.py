"""Exercise the running stack; keep one reusable document in template_smoke."""

import asyncio
import json
import os
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx

from app.modules.ai.domain import DocumentInput, DocumentStatus, QueryResponse
from app.modules.ai.router import AIStatus

_NAMESPACE = "template_smoke"
_DOCUMENT_ID = uuid5(NAMESPACE_URL, "template-ai:smoke:langgraph:v1")
_EVIDENCE = "LangGraph uses StateGraph to define workflows."


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


async def main() -> None:
    base_url = os.getenv("AI_SMOKE_BASE_URL", "http://127.0.0.1:8080")
    payload = DocumentInput.model_validate(
        {
            "namespace": _NAMESPACE,
            "title": "LangGraph starter",
            "text": _EVIDENCE
            + " This starter stores source documents and knowledge claims in Neo4j."
            + " Vector search is handled by Qdrant.",
            "facts": [
                {
                    "subject": {"name": "LangGraph", "kind": "library"},
                    "predicate": "uses",
                    "object": {"name": "StateGraph", "kind": "API"},
                    "evidence": _EVIDENCE,
                }
            ],
        }
    )
    path = f"/api/v1/ai/documents/{_DOCUMENT_ID}"
    async with httpx.AsyncClient(base_url=base_url, timeout=60) as client:
        response = await client.get("/api/v1/ai/status")
        response.raise_for_status()
        require(AIStatus.model_validate(response.json()).enabled, "AI must be enabled")
        for _ in range(2):
            response = await client.put(path, json=payload.model_dump(mode="json"))
            response.raise_for_status()
            require(
                DocumentStatus.model_validate(response.json()).status == "ready",
                "Indexing must finish before retrieval",
            )
        response = await client.get(path, params={"namespace": _NAMESPACE})
        response.raise_for_status()
        require(
            DocumentStatus.model_validate(response.json()).status == "ready",
            "SQL must retain ready status",
        )
        changed = payload.model_copy(update={"title": "Different immutable content"})
        response = await client.put(path, json=changed.model_dump(mode="json"))
        require(response.status_code == 409, "Different content must conflict")
        response = await client.post(
            "/api/v1/ai/query",
            json={
                "namespace": _NAMESPACE,
                "question": "What does LangGraph use to define workflows?",
            },
        )
        response.raise_for_status()
        result = QueryResponse.model_validate(response.json())
        require(bool(result.answer.strip()), "The model must return an answer")
        require(
            any(source.document_id == _DOCUMENT_ID for source in result.sources),
            "Retrieval must include the indexed source",
        )
        require(
            any(fact.evidence == _EVIDENCE for fact in result.facts),
            "Knowledge claims must retain source evidence",
        )
        response = await client.post(
            "/api/v1/ai/query",
            json={"namespace": f"empty_{uuid4().hex}", "question": "Any sources?"},
        )
        response.raise_for_status()
        empty = QueryResponse.model_validate(response.json())
        require(not empty.sources and not empty.facts, "Namespaces must be isolated")
    print(
        json.dumps(
            {
                "status": "passed",
                "checks": ["ingest", "retry", "sql_status", "conflict", "rag", "namespace"],
                "sources": len(result.sources),
                "facts": len(result.facts),
                "namespace": _NAMESPACE,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
