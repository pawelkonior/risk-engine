Architecture and source analysis
================================

Baseline
--------

This starter adapts ``flashcards_pro/templates/fastapi-microservice`` rather
than copying the Flashcard Pro product domain. The source template supplies
feature-oriented modules, component settings, JSON logs, request correlation,
body limits, CORS, stable operation IDs, public error envelopes and health
probes. These boundaries remain useful when building a new application.

The local quality gates retain Ruff lint and format, strict Pyright, branch
coverage of at least 90%, Sphinx warnings as errors, locked dependencies and
tox. Local pre-commit hooks run the full gate without modifying source files.

Persistence changes
-------------------

The source template makes PostgreSQL optional, only accepts asyncpg URLs and
has an empty initial migration. Here persistence is mandatory. Aiosqlite
supports local SQLite and psycopg supports PostgreSQL, including provider
URLs using ``postgres://`` and ``postgresql://``. The initial migration creates
the example items table. Foreign-key checks are enabled for SQLite.

Models use database-neutral UUIDs and UTC timestamps, including normalization
when reading from SQLite. Services perform queries and own explicit commits;
request dependencies provide
isolated sessions with rollback on errors. No schema creation or migration
runs as an import or application startup side effect.

Runtime and deployment
----------------------

``create_app`` assembles the application with a lazy database engine. Lifespan
manages process resources, while readiness checks the required database. The
entrypoint ``index.py`` exports the ASGI app for native FastAPI deployment.

Vercel instances do not share persistent local files, so SQLite is rejected
when ``VERCEL=1``. Hosted PostgreSQL is required there. ``null`` pool mode
avoids retaining connections in suspended serverless instances; external
transaction poolers can manage the shared connection budget. Psycopg prepared
statements are disabled for compatibility with such poolers. A separate
migration URL can bypass the runtime pooler.

The latest FastAPI requires the ``opentelemetry-api`` facade. The starter
installs no OpenTelemetry SDK or automatic exporters. Its native tracing, metrics,
telemetry logs, operation spans and automatic environment setup are explicitly
disabled, including when a host sets ``FASTAPI_OTEL_AUTO_CONFIGURE=true``.
Application JSON logs stay on stdout and preserve request correlation without
a telemetry collector.

Application modules
-------------------

The dependency flow is ``router -> service -> database``. Schemas describe
the HTTP contract. Services contain queries and use cases without importing
FastAPI. For more complex persistence, a repository can be extracted later.
The HTTP dependency layer composes adapters at the edge.

The public ``items`` CRUD is a working example of this pattern. Authentication
and per-user authorization are application-specific and are not implemented
by this generic starter. Add them before exposing user-owned records.

Health probes are unversioned; business routes live under ``/api/v1``. CORS is
opt-in. Middleware assigns a safe request ID, bounds request bodies, and emits
an access log. Application errors map to a stable HTTP envelope.
