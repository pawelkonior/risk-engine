# Wersje i zgodność

Stan zweryfikowany **17 listopada 2026 r.** Wersje bezpośrednich zależności aplikacji sprawdzono w rejestrach npm i PyPI; obrazy i runtime w oficjalnych źródłach dostawców. Używamy stabilnych wydań oraz wspieranych linii runtime. Zależności aplikacji są przypięte, a `web/package-lock.json` i `api/uv.lock` utrwalają również pełne drzewo zależności.

„Najnowsze” oznacza stabilne wydanie spełniające kontrakt zgodności projektu. Nie wybieramy kanałów alpha, beta, RC ani canary; runtime backendu musi być dostępny na Vercel. Zestawienie jest datowanym punktem odniesienia, a nie automatyczną aktualizacją do przyszłych wydań.

## Frontend i narzędzia

| Składnik                            | Wersja   |
| ----------------------------------- | -------- |
| Node.js, linia LTS                  | 26.13.1  |
| npm                                 | 12.2.2   |
| React / React DOM                   | 19.3.1   |
| TypeScript                          | 7.0.2    |
| Vite                                | 8.3.8    |
| `@vitejs/plugin-react`              | 6.3.0    |
| TanStack Query                      | 5.107.2  |
| Zod                                 | 4.6.7    |
| Playwright                          | 1.65.1   |
| `@axe-core/playwright`              | 4.14.0   |
| Vitest / `@vitest/coverage-v8`      | 5.1.0    |
| Testing Library React               | 16.3.3   |
| Testing Library DOM                 | 10.4.2   |
| Testing Library jest-dom            | 7.0.1    |
| Testing Library user-event          | 14.6.12  |
| jsdom                               | 31.0.1   |
| Oxlint                              | 1.94.0   |
| `oxlint-tsgolint`                   | 7.0.2007 |
| Prettier                            | 3.10.1   |
| `@types/react` / `@types/react-dom` | 19.3.0   |
| `@types/node`                       | 26.6.6   |

Źródła wersji: [rejestr npm React](https://registry.npmjs.org/react/latest), [TypeScript](https://registry.npmjs.org/typescript/latest), [Vite](https://registry.npmjs.org/vite/latest), [Playwright](https://registry.npmjs.org/@playwright%2ftest/latest), [Vitest](https://registry.npmjs.org/vitest/latest), [Oxlint](https://registry.npmjs.org/oxlint/latest), [Prettier](https://registry.npmjs.org/prettier/latest) oraz pozostałe wpisy pakietów w npm. Runtime: [wydania Node.js](https://nodejs.org/en/about/previous-releases), [npm](https://github.com/npm/cli/releases).

### TypeScript 7 i lintowanie

Strict `tsc` sprawdza cały kod aplikacji, konfiguracje i E2E. Lint z informacją o typach zapewniają Oxlint i `oxlint-tsgolint`, z regułami TypeScript, React i dostępności. W dniu weryfikacji najnowszy `typescript-eslint` deklarował TypeScript `<6.1` jako peer dependency. Zastosowanie go z TS 7 wymagałoby pominięcia deklarowanej zgodności, dlatego w tym starterze wybrano Oxlint.

Źródła: [zgodność typescript-eslint](https://typescript-eslint.io/users/dependency-versions/), [metadane peer dependencies w npm](https://registry.npmjs.org/typescript-eslint/latest), [Oxlint type-aware linting](https://oxc.rs/docs/guide/usage/linter/type-aware.html).

## Backend

| Składnik                       | Wersja     |
| ------------------------------ | ---------- |
| Python, wspierana linia Vercel | 3.14.10    |
| uv w obrazie Docker            | 0.13.9     |
| FastAPI                        | 0.163.1    |
| Pydantic                       | 2.14.3     |
| pydantic-settings              | 2.16.3     |
| SQLAlchemy                     | 2.1.9      |
| Alembic                        | 1.20.1     |
| psycopg                        | 3.3.9      |
| aiosqlite                      | 0.22.1     |
| Uvicorn                        | 0.54.0     |
| python-json-logger             | 4.2.0      |
| HTTPX (runtime REST)           | 0.28.1     |
| LangGraph                      | 1.2.22     |
| Neo4j Python driver            | 6.4.1      |
| pre-commit                     | 4.7.0      |
| Ruff                           | 0.17.5     |
| Pyright                        | 1.1.414    |
| pytest                         | 9.2.0      |
| pytest-asyncio                 | 1.5.0      |
| pytest-cov                     | 7.1.0      |
| tox                            | 4.67.13    |
| tox-uv                         | 1.37.7     |
| Sphinx                         | 9.2.0      |
| Furo                           | 2025.12.19 |
| Hatchling, backend builda      | 1.33.0     |

Źródła: [FastAPI w PyPI](https://pypi.org/pypi/fastapi/json), [SQLAlchemy](https://pypi.org/pypi/sqlalchemy/json), [Pydantic](https://pypi.org/pypi/pydantic/json), [Ruff](https://pypi.org/pypi/ruff/json) i metadane pozostałych pakietów PyPI. [Wydania uv](https://github.com/astral-sh/uv/releases), [wydania Python](https://www.python.org/downloads/), [wspierane wersje runtime Vercel](https://vercel.com/docs/functions/runtimes/python).

Python 3.14.10 jest najnowszym patchem linii obsługiwanej przez Vercel. Nowsza stabilna linia Python 3.15 nie jest tam jeszcze dostępna, dlatego podniesienie backendu do niej uniemożliwiłoby zachowanie tego samego runtime lokalnie, w kontenerze i na Vercel.

Aktualny FastAPI wymaga pakietu `opentelemetry-api` jako zależności pośredniej. Jest to fasada API; starter nie instaluje OpenTelemetry SDK ani automatycznych exporterów. Langfuse ma jawny adapter publicznego OTLP HTTP/JSON, bez dodatkowych zależności Pythona. Tracing, metryki, eksport logów, operation spans i automatyczna konfiguracja telemetrii są jawnie wyłączone w fabryce aplikacji. Logi aplikacji nadal trafiają jako JSON na stdout.

LangGraph używa własnego `StateGraph`, bez LangChain model integrations, checkpointera i zewnętrznego serwera LangGraph. Pakiet wprowadza pośrednio `langchain-core` i `langsmith`; tracing LangSmith jest jawnie wyłączany w kodzie. Nie instalujemy SDK Ollamy, Qdrant, FastEmbed ani modeli w funkcji Vercel. Adaptery korzystają z HTTPX REST, a Neo4j z oficjalnego sterownika. [LangGraph PyPI](https://pypi.org/pypi/langgraph/json), [sterownik Neo4j PyPI](https://pypi.org/pypi/neo4j/json), [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview).

Domyślne modele lokalne to `qwen3:0.6b` oraz `embeddinggemma` (768 wymiarów). Przykład chmurowy używa `@cf/meta/llama-3.1-8b-instruct` i `intfloat/multilingual-e5-small` (384 wymiary). Wymagają osobnych kolekcji i reindeksacji; nie są zamiennymi przestrzeniami wektorowymi. Tagi modeli Ollamy mogą być aktualizowane przez dostawcę — digest pobranego modelu pokazuje `ollama list`. [Modele Ollama](https://ollama.com/library), [Qdrant Cloud Inference](https://qdrant.tech/documentation/embeddings/qdrant-cloud-inference/).

## Kontenery

| Obraz                    | Wybrany tag                                                    |
| ------------------------ | -------------------------------------------------------------- |
| Node do builda frontendu | `node:26.13.1-alpine`                                          |
| Nginx bez roota          | `nginx/nginx-unprivileged:1.30.6-alpine`                       |
| Python API               | `python:3.14.10-slim-trixie`                                   |
| uv do builda API         | `ghcr.io/astral-sh/uv:0.13.9`                                  |
| PostgreSQL               | `postgres:18.7-alpine`                                         |
| Neo4j Community          | `neo4j:2026.10.2-community`                                    |
| Qdrant bez roota         | `qdrant/qdrant:v1.20.2-unprivileged`                           |
| Langfuse web / worker    | `langfuse/langfuse:4.82.0` / `langfuse/langfuse-worker:4.82.0` |
| ClickHouse               | `clickhouse/clickhouse-server:26.10.5.57`                      |
| Redis                    | `redis:8.10.3-alpine`                                          |
| RustFS S3                | `rustfs/rustfs:1.0.6`                                          |
| S3 bucket bootstrap      | `rustfs/rc:v0.1.37`                                            |
| Ollama                   | `ollama/ollama:0.40.16`                                        |

PostgreSQL 18.7 jest stabilnym wydaniem; kanał 19 RC został pominięty. Nginx 1.30.6 pochodzi ze stabilnej linii, a linia 1.31 mainline nie została wybrana. Node 26 jest linią LTS; wydania Node 27 alpha nie są częścią konfiguracji.

Źródła: [wersjonowanie PostgreSQL](https://www.postgresql.org/support/versioning/), [wydania Nginx](https://nginx.org/en/download.html), [obrazy Nginx unprivileged](https://github.com/nginx/docker-nginx-unprivileged), [oficjalne obrazy Node](https://hub.docker.com/_/node), [Python](https://hub.docker.com/_/python), [PostgreSQL](https://hub.docker.com/_/postgres).

[Wydania Neo4j](https://neo4j.com/release-notes/), [Qdrant](https://github.com/qdrant/qdrant/releases), [Ollama](https://github.com/ollama/ollama/releases) oraz oficjalne obrazy dostawców były źródłem wersji usług AI.

Tagi patchowe ograniczają przypadkową zmianę wersji serwera, lecz dostawca może przebudować obraz bazowy pod tym samym tagiem. Dla wydania wymagającego identycznych bajtów obrazu można dodatkowo przypiąć digest po wybraniu docelowej platformy.

## Odtwarzanie i aktualizacje

`npm ci` i `uv sync --locked` odtwarzają zapisane zależności. Przy aktualizacji zmień przypięte wersje, odśwież locki i wykonaj lokalne gates oraz oba warianty E2E:

```bash
make check
make e2e
docker compose up --build --wait
make e2e-compose
```

Nie ma automatycznego audytu zależności ani GitHub Actions. Kontrole jakości działają lokalnie i przez pre-commit, zgodnie z przyjętym sposobem pracy.

## Langfuse compatibility

The template pins self-hosted Langfuse 4.82.0 and uses native v4 OTLP HTTP/JSON.
It does not install the Python SDK; the current SDK release is 5.2.0, which is a
separate version line. Legacy Cloud trace ingestion reached sunset on November
16, 2026. Compatibility is defined by the public OTLP endpoint and ingestion
header. [Release](https://github.com/langfuse/langfuse/releases/tag/v4.82.0),
[compatibility matrix](https://langfuse.com/docs/compatibility),
[OpenTelemetry integration](https://langfuse.com/integrations/native/opentelemetry).

Infrastructure image tags were verified in their official registries for AMD64
and ARM64. Langfuse's PostgreSQL uses the same supported 18.7 image as the
application, with a separate service and volume. Compose must be at least 2.23.1
for the inline ClickHouse configuration.

## Agent tooling

Verified on November 18, 2026. Eleven additional official skills are pinned to
full upstream commit SHAs in [.agents/skills.lock.json](../.agents/skills.lock.json).
The existing Spec Kit 1.4.1 integration remains separate.

| Tool | Version / source |
| --- | --- |
| Playwright browser CLI | Existing stable Playwright 1.65.1, through `playwright cli` |
| Langfuse CLI | `@langfuse/cli` 1.3.1, separate npm lock |
| Neo4j MCP | `neo4j-mcp-server` 2.1.1, isolated uv script lock |
| Neo4j MCP environment loader | `python-dotenv` 1.2.4, isolated uv script lock |
| APOC Core | 2026.10.2, bundled in the pinned Neo4j image |
| Codex configuration compatibility | Verified with local Codex 0.169.0 |

The standalone `@playwright/cli` package pins alpha Playwright builds. The template
uses Microsoft's documented local `playwright cli` mode to retain stable browser
tooling without overriding upstream dependencies. Additional agent tools do not
change application dependency locks or Vercel builds. Hosted MCP implementations
are maintained by their providers and cannot be pinned to a local server release.

Sources: [Microsoft local installation](https://github.com/microsoft/playwright-cli#local-installation),
[Langfuse CLI package](https://www.npmjs.com/package/@langfuse/cli),
[Neo4j MCP 2.1.1](https://github.com/neo4j/mcp/releases/tag/v2.1.1),
[APOC installation](https://neo4j.com/docs/apoc/current/installation/).
See [agent tooling](agent-tooling.md) for setup, authentication, and scope.
