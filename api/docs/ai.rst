AI workflow
===========

The optional AI module uses LangGraph for a stateless, bounded retrieval workflow.
The default local providers are Ollama, Neo4j Community, and Qdrant. PostgreSQL or
SQLite remains mandatory and records indexing progress in ``ai_index_records``.

Data flow
---------

Ingestion reserves an immutable document identity in SQL, writes Qdrant vectors,
commits the Neo4j source and knowledge graphs, and finally marks the SQL record
``ready``. Retrieval uses only ready documents with the active embedding profile.
An interrupted ingestion can be retried with the same UUID and body.

The knowledge graph stores entities and claims. The source graph stores documents,
ordered chunks, and exact evidence. Claims link to their supporting chunks.
Facts are supplied explicitly by the caller; there is no automatic extraction.

Operations
----------

``GET /api/v1/ai/status`` reports configuration without connecting to services.
``PUT /api/v1/ai/documents/{id}`` indexes a source, and
``GET /api/v1/ai/documents/{id}?namespace=default`` reads its status.
``POST /api/v1/ai/query`` retrieves source chunks and claims, then calls the model.
Queries without sources skip generation.

Root Docker Compose explicitly runs model downloads, SQL migrations, and AI schema
initialization before API startup. For external services, run
``python -m app.platform.ai.setup`` separately before deployment. Requests never
create schema or download models. The request deadline is 45 seconds by default.

Vercel uses external HTTPS model and Qdrant endpoints and a TLS Neo4j endpoint.
No clients or connections are shared across event loops. LangSmith and Neo4j
driver telemetry are explicitly disabled. JSON application logs are preserved.

Langfuse observations
---------------------

Root Compose enables explicit Langfuse AI observations. A bare API keeps them
disabled until the endpoint and both project keys are configured. Each request
buffers its own root and stage spans and exports public OTLP HTTP/JSON with
native v4 ingestion. No Langfuse SDK or global tracer provider is installed.

Function-scoped dependency cleanup awaits the bounded export before the HTTP
response starts. Export errors do not replace the AI result. Metadata is recorded
by default; input and output content require explicit opt-in. Raw exception
messages are never exported. See ``docs/langfuse.md`` at the repository root for
local credentials, Cloud configuration, and privacy controls.

See ``docs/ai.md`` at the repository root for complete setup, REST examples,
managed-service limits, and embedding migration instructions.
