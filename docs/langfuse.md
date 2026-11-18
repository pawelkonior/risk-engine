# Langfuse

The template records AI ingestion and query traces in Langfuse. Docker Compose enables a local Langfuse v4 instance. A bare API process keeps observability disabled until `APP_LANGFUSE_ENABLED=true` and both project keys are configured.

Start the stack from the repository root:

```sh
cp .env.example .env
make up
```

Copy the example only when creating your local `.env`; preserve any existing configuration. Open [local Langfuse](http://localhost:3000) and sign in with the development account created by Compose:

| Setting              | Local default              |
| -------------------- | -------------------------- |
| Email                | `developer@example.test`   |
| Password             | `Langfuse-local-only-2026` |
| Organization/project | `Template AI`              |
| Public project key   | `pk-lf-template-local`     |
| Secret project key   | `sk-lf-template-local`     |

These are published development defaults. Configure separate project keys and credentials for deployed environments. Headless initialization uses the persistent Langfuse database; changing an initialization variable does not replace an existing account or project.

Run the end-to-end trace check after the stack is healthy:

```sh
make langfuse-smoke
```

The smoke workflow uses one persistent source in the `langfuse_smoke` namespace. Repeated runs reuse that source. Inspect the resulting ingestion/query observations in the local project. The application can finish a request before Langfuse's worker has made its observations available for querying.

The local platform has its own persistent infrastructure:

| Compose service       | Responsibility                                                                |
| --------------------- | ----------------------------------------------------------------------------- |
| `langfuse-web`        | UI, public APIs and trace ingestion; port `3000` on loopback                  |
| `langfuse-worker`     | Background event processing                                                   |
| `langfuse-postgres`   | Langfuse accounts, projects and transactional data                            |
| `langfuse-clickhouse` | Observations and analytical data                                              |
| `langfuse-redis`      | Queue and cache                                                               |
| `langfuse-s3`         | RustFS object storage; browser-accessible S3 endpoint on loopback port `9090` |
| `langfuse-s3-init`    | Creates the local S3 bucket                                                   |

Langfuse PostgreSQL has separate credentials and a separate volume from the application's PostgreSQL. Its data does not become part of the application's Alembic schema. The storage roles follow [Langfuse's self-hosted architecture](https://langfuse.com/self-hosting). Compose uses [RustFS's S3-compatible storage](https://github.com/rustfs/rustfs); the [MinIO repository was archived in April 2026](https://github.com/minio/minio).

`make down` stops the containers and preserves their named volumes. Local credentials, ports and infrastructure settings are listed in the root `.env.example`.

The API configuration uses the application's `APP_` namespace:

| API setting                    | Default                 | Purpose                                                                        |
| ------------------------------ | ----------------------- | ------------------------------------------------------------------------------ |
| `APP_LANGFUSE_ENABLED`         | `false`                 | Enable explicit AI observations                                                |
| `APP_LANGFUSE_BASE_URL`        | `http://127.0.0.1:3000` | Local, Cloud or self-hosted Langfuse base URL                                  |
| `APP_LANGFUSE_PUBLIC_KEY`      | Unset                   | Project public key                                                             |
| `APP_LANGFUSE_SECRET_KEY`      | Unset                   | Project secret key                                                             |
| `APP_LANGFUSE_CAPTURE_CONTENT` | `false`                 | Include application inputs and outputs                                         |
| `APP_LANGFUSE_TIMEOUT_SECONDS` | `3`                     | Maximum export time; supported range is greater than zero through five seconds |

For a host-run API, configure these variables in `api/.env` or the process environment. Compose supplies the API variables from the root `LANGFUSE_*` settings and uses the internal URL `http://langfuse-web:3000`. Changes to Compose environment settings take effect when the affected containers are recreated.

Content capture is opt-in. Default traces contain operation names, timing, hierarchy, model names, request correlation, namespace/document identifiers, collection/profile identity, counts and status. Prompts, source text, titles, facts and generated answers are excluded from the observation input/output fields. Exception messages are excluded; failures use an error type. The metadata fields still contain identifiers, so choose namespace and document identifiers with the intended audience in mind.

To capture content locally, set `LANGFUSE_CAPTURE_CONTENT=true` in the root `.env` and recreate the API container. For a bare API or Vercel, use `APP_LANGFUSE_CAPTURE_CONTENT=true`. This includes questions, uploaded source content, model prompts and responses; enable it only for data that may be stored in the selected Langfuse project. Content and span counts are bounded. Token-usage and model-cost fields are not exported by this template.

The application uses a small asynchronous HTTP adapter for the public OTLP HTTP/JSON protocol. It sends one buffered request's spans to `/api/public/otel/v1/traces`, authenticates with the project key pair, and sets `x-langfuse-ingestion-version: 4` for native v4 ingestion. Langfuse documents the endpoint, authentication and JSON support in its [OpenTelemetry integration](https://langfuse.com/integrations/native/opentelemetry). Legacy batch trace ingestion and legacy trace read APIs reached their Cloud sunset on November 16, 2026; use the current [compatibility matrix](https://langfuse.com/docs/compatibility) when extending the adapter.

This adapter deliberately keeps the integration limited to application trace export. It adds no Langfuse SDK, global tracer provider, automatic HTTP instrumentation or background SDK exporter. Each AI request owns its observation buffer and HTTP client. LangSmith tracing remains disabled independently.

FastAPI declares the service dependency with `Depends(..., scope="function")`. Its cleanup awaits trace export and closes the client before the HTTP response starts. This follows [FastAPI's function-scope dependency lifecycle](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/#early-exit-and-scope) and avoids relying on process shutdown or a background thread surviving Vercel's invocation. Langfuse explains the event-loss risk in [its serverless guidance](https://langfuse.com/faq/all/aws-lambda-and-serverless-functions). A bounded export can add up to the configured timeout to response latency.

Trace export fails open: a network error, timeout or failed ingestion response produces the fixed log message `Langfuse trace export failed` and leaves the AI result unchanged. Missing observability therefore does not fail an otherwise successful AI request. With observability disabled, the dependency creates no exporter HTTP client.

For Vercel, keep the existing two projects: frontend Root Directory `web`, backend Root Directory `api`. Set the backend variables from `api/.env.vercel.example`, using keys from the destination Langfuse project:

```dotenv
APP_LANGFUSE_ENABLED=true
APP_LANGFUSE_BASE_URL=https://cloud.langfuse.com
APP_LANGFUSE_PUBLIC_KEY=REPLACE_WITH_LANGFUSE_PUBLIC_KEY
APP_LANGFUSE_SECRET_KEY=REPLACE_WITH_LANGFUSE_SECRET_KEY
APP_LANGFUSE_CAPTURE_CONTENT=false
APP_LANGFUSE_TIMEOUT_SECONDS=3
```

Use the URL for your Cloud region or an externally hosted Langfuse v4 instance. Vercel validation requires external HTTPS and rejects local template keys. Keep both keys in backend environment variables. The frontend needs no Langfuse credentials. The self-hosted Compose infrastructure runs locally; Vercel connects to the external Langfuse endpoint.

As checked on November 17, 2026, [Langfuse Cloud Hobby](https://langfuse.com/pricing) is free without a credit card and includes 50,000 units per month, two users and a 30-day historical data-access window. Units are a usage allowance, not a promise of 50,000 complete multi-step application requests. Older data falls outside the access window; the window itself does not delete that data. Langfuse distinguishes this from configurable retention in its [data-access FAQ](https://langfuse.com/faq/all/data-access-vs-data-retention).

The Compose platform disables its own usage telemetry with `TELEMETRY_ENABLED=false` on both Langfuse application containers. Next.js telemetry, automatic platform instrumentation, Datadog exports and RustFS exports are disabled while local logs remain available. Signup onboarding, Halo and the AI Gateway are disabled. These settings are independent of the explicitly enabled application-to-Langfuse trace export.

There are documented remaining external UI requests: Langfuse's Web container checks for updates when an authenticated user loads the UI, and that check has no configuration switch. Browser UI assets can also come from external hosts. Compose pulls the Langfuse images directly from Docker Hub, avoiding the adoption-tracking registry proxy at `docker.langfuse.com`. See the platform's [telemetry and outbound-host documentation](https://langfuse.com/self-hosting/security/telemetry) for the precise scope.

The official [`langfuse` skill](https://github.com/langfuse/skills/blob/main/skills/langfuse/SKILL.md) is installed for Codex and covers tracing, prompts, datasets and evaluations. The separate [`migrate-to-langfuse` skill](https://github.com/langfuse/skills/blob/main/skills/migrate-to-langfuse/SKILL.md) concerns migration from another provider and is not installed. The [agent tooling guide](agent-tooling.md) describes the pinned CLI, credential mapping, and documentation MCP. Local evaluation commands remain compatible with the project's pre-commit workflow; this integration adds no GitHub Actions.

The [Langfuse Codex observability plugin](https://github.com/langfuse/codex-observability-plugin) captures the coding agent's own sessions, tools and prompts. It is a separate integration and is not installed or enabled here.
