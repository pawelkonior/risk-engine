Operations
==========

Versions
--------

Direct dependencies are pinned to the latest stable PyPI releases verified on
2026-11-17. The lockfile pins their complete resolved dependency graph.
Python 3.14.10 is the latest patch of the newest Python line supported by the
Vercel runtime; Python 3.15 is not selected because that host does not support
it yet. The container uses Python 3.14.10 on Debian Trixie and uv 0.13.9.

Configuration
-------------

Settings use ``APP_`` environment variables and an optional ``.env``. Unknown
``APP_`` names fail validation. Production mode requires API documentation to
be disabled. Configure browser origins explicitly as a JSON array.

``APP_DATABASE_URL`` defaults to local SQLite. ``DATABASE_URL`` is accepted as
an alias; configure one URL variable. Supported databases are PostgreSQL and
SQLite. ``APP_DATABASE_MIGRATION_URL`` optionally overrides the runtime URL
for Alembic only.

Migration workflow
------------------

Run ``uv run alembic upgrade head`` as an explicit release action, before the
new application serves traffic. Run ``uv run alembic check`` afterward to
verify ORM/schema consistency. Review generated migration code before release.
Never run migrations concurrently from application startup or preview builds.
Use isolated databases for preview deployments and integration tests.

Health and logs
---------------

``/health/live`` reports process liveness. ``/health/ready`` queries the required
database and returns 503 when it cannot respond within the readiness timeout.
Readiness does not replace migration validation.

Logs are JSON on stdout. A safe incoming ``X-Request-ID`` is preserved; absent
or unsafe IDs are replaced with a UUID. Correlation is available in responses,
access logs and error envelopes. Do not add authorization headers, payloads,
secrets or complete database URLs to application log fields. Access logs use
route templates rather than raw URL paths and omit query strings. Unexpected
exceptions record exception classes and safe stack frames without exception
messages or SQL parameters. Request bodies are buffered up to the configured
limit before handlers run; the default limit is 1 MiB.

Vercel
------

Set Root Directory to ``api`` in this repository. The native Python/FastAPI
preset reads ``pyproject.toml``, ``uv.lock`` and the ``index:app`` entrypoint.
``vercel.json`` configures a 60-second function duration without legacy
builders or manual rewrites. Put production environment variables in Vercel
settings, including the PostgreSQL URL, ``APP_ENVIRONMENT=production``,
``APP_DOCS_ENABLED=false`` and ``APP_DATABASE_POOL_MODE=null``. Use provider
TLS requirements and a region close to the database.

SQLite files cannot provide durable storage on Vercel. Shutdown cleanup is
best effort and must not be required for durable writes. Run migrations using
a controlled external release step, with a direct database URL where needed.

Official references checked on 2026-11-17:

* `Python runtime <https://vercel.com/docs/functions/runtimes/python>`_
* `FastAPI deployment <https://vercel.com/docs/frameworks/backend/fastapi>`_
* `Function filesystem <https://vercel.com/docs/functions/runtimes#file-system-support>`_

Containers
----------

The image runs as UID/GID 10001 on port 8000. The standalone default SQLite
path is ``/app/data/app.db``; provide a writable persistent volume for durable
data. Compose uses PostgreSQL with a named volume, health checks, a read-only
API filesystem and an unprivileged process. Run migrations explicitly before
starting the API.

Local quality gates
-------------------

``make check`` installs locked dependencies and runs the tox quality
environments: Ruff, format checks, strict Pyright, pytest with at least 90%
branch coverage, and Sphinx warnings as errors. Local SQLite tests require no
container daemon. Set ``TEST_DATABASE_URL`` only to an isolated test database
to additionally exercise PostgreSQL.

After creating a Git repository, install the local commit hooks from this
repository root using ``uv run --project api pre-commit install``. Run all
checks explicitly with ``uv run --project api pre-commit run --all-files``.
The root configuration handles the backend in the ``api`` directory.

The configuration included inside ``api`` handles a standalone repository
containing the contents of that directory at its root. There, use
``uv run pre-commit install`` and ``uv run pre-commit run --all-files``.
Both configurations use local project tools and perform checks without
automatic source changes. Use ``make format`` when you deliberately want
formatting and automatic lint fixes.
