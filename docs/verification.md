# Wyniki weryfikacji

Weryfikacja wykonana 17 listopada 2026 r. na macOS ARM64, Node 26.13.1, npm 12.2.2 i Python 3.14.10. Kontenery zbudowano i uruchomiono przez Docker Compose.

| Obszar                                                       | Wynik                                                                                                              |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| API: poprzednia pełna weryfikacja SQLite/PostgreSQL i baz AI | 263 testy, wszystkie przeszły                                                                                      |
| API: coverage z pomiarem linii i gałęzi                      | 96,70%, wymagane co najmniej 90%                                                                                   |
| Web: Vitest i Testing Library                                | 29 testów, wszystkie przeszły                                                                                      |
| Web: coverage                                                | 98,49% instrukcji, 94,89% gałęzi, 100% linii i funkcji                                                             |
| Playwright: produkcyjny build + izolowane SQLite API         | 12 scenariuszy, wszystkie przeszły                                                                                 |
| Playwright: Nginx + FastAPI + PostgreSQL w Compose           | 12 scenariuszy, wszystkie przeszły                                                                                 |
| Przeglądarki                                                 | Chromium, Firefox, WebKit, mobilny Chromium                                                                        |
| Dostępność                                                   | Automatyczne testy axe WCAG 2/2.1 A i AA oraz szerokość widoku                                                     |
| Lokalne quality gates                                        | Ruff, format, strict Pyright, Oxlint type-aware, strict TypeScript, Prettier i Sphinx z ostrzeżeniami jako błędami |
| Pre-commit                                                   | Wszystkie 11 hooków przeszły; hook E2E obejmuje Chromium i build produkcyjny                                       |
| Kontenery                                                    | Build API i web przeszedł; 12 usług healthy; migracje, modele, indeksy i inicjalizacja S3 exit 0                   |
| Restart                                                      | Rekord PostgreSQL przetrwał restart bazy, API i Nginx; odczyt i usunięcie po powrocie gotowości przeszły           |
| Hasła bazy                                                   | Potwierdzono połączenie z hasłem zawierającym znaki specjalne przez PGPASSWORD, bez umieszczania hasła w URI       |
| Wersje npm                                                   | Wszystkie 22 bezpośrednie zależności zgadzały się z tagiem latest stabilnego wydania                               |
| Vercel API                                                   | Import entrypointu bez połączenia z bazą, NullPool i wyłączona dokumentacja produkcyjna                            |

Testy API obejmują migracje upgrade, kontrolę zgodności schematu, downgrade i ponowny upgrade dla obu silników. Do testów PostgreSQL utworzono osobną bazę, która została usunięta po zakończeniu. Testy przeglądarkowe sprawdzają stronę z tekstem „Aplikacja działa.”, połączenie API przez proxy, CRUD klienta HTTP i niezależność strony od API. Sprzątają wyłącznie własne rekordy.

W teście restartów poprawiono healthcheck frontendu: stan healthy wymaga również poprawnej odpowiedzi API przez proxy.

Uruchomienie samego pre-commit bez TEST_DATABASE_URL korzysta z SQLite i pomija dwa warianty PostgreSQL oraz dwa testy realnych adapterów AI. Pełny test z osobną bazą PostgreSQL 18.7 wykonano niezależnie. Telemetria platform pozostaje wyłączona; jawny eksport operacji AI do Langfuse jest oddzielną konfiguracją. Nie uruchamiano audytu zależności ani GitHub Actions.

Instalację i build frontendu z `web/vercel.json` sprawdzono również w czystym kontenerze Node 26 startującym z npm 11, z plikami odpowiadającymi uploadowi Vercel. Przypięty npm 12.2.2 uruchomiony przez npx wykonał `npm ci` i produkcyjny build poprawnie.

Konfiguracja Vercel jest przygotowana do wdrożenia. Weryfikacja nie obejmowała publikacji aplikacji na koncie Vercel. Aktualne wersje i źródła opisuje [versions.md](versions.md).

## LangGraph i bazy AI

Uruchomiono rzeczywiste Neo4j Community 2026.10.2, Qdrant 1.20.2 i Ollamę 0.40.16. Compose pobrał qwen3:0.6b i embeddinggemma do trwałego wolumenu. Jawne zadanie `ai-init` utworzyło constraints i kolekcję bez DDL podczas importu lub requestów.

`make ai-smoke` sprawdził ingest, ponowienie identycznego zapisu, status SQL, konflikt zmienionej treści, odpowiedź rzeczywistej Ollamy ze źródłem i faktem oraz izolację namespace. Smoke zachowuje jeden własny dokument w `template_smoke`. Dwa niezależne testy prawdziwych adapterów sprawdziły oba grafy, krawędzie NEXT, zachowanie proweniencji, izolację namespace i profilu embeddingów, konflikt hasha oraz usuwanie źródła bez usuwania współdzielonej encji. Własne kolekcje i namespace’y testowe zostały posprzątane.

Testy jednostkowe obejmują przerwania i retry indeksowania, wyścig dwóch sesji SQL, zachowanie statusu ready przy spóźnionej awarii, brak źródeł bez generowania odpowiedzi, nieznane cytowania, niezaufany kontekst w user message, limity i anulowanie żądań, zamykanie transportów oraz wyłączenie LangSmith mimo tracingu w środowisku hosta.

Wyłączono telemetry Neo4j server/driver, raportowanie użycia, Fleet Manager, discovery i telemetry klientów, a także Qdrant telemetry oraz Ollama Cloud. JSON logi aplikacji pozostały włączone. Neo4j zaakceptował konfigurację; po restarcie nie zgłaszał włączonego discovery.

Wykryto, że istniejący test migracji pozwalał wskazać zwykłą bazę aplikacji. Dodano wymóg nazwy `test_*` i testy odrzucające bazy aplikacyjne/systemowe przed uruchomieniem migracji. Schemat lokalnej bazy Compose został odtworzony po omyłkowym teście downgrade; docelowy przebieg wykonano na oddzielnej `test_template_ai`.

Przykładowe ustawienia Vercel przechodzą walidację dla zewnętrznych TLS/HTTPS endpointów i PostgreSQL z NullPool. Nie wykonano deploymentu ani rzeczywistych wywołań AuraDB, Qdrant Cloud, Neon lub Cloudflare Workers AI. Kontrakty HTTP obu providerów i konfigurację chmurową sprawdzono lokalnie; limity planów udokumentowano z oficjalnych źródeł w [ai.md](ai.md).

LangSmith 0.15.0 zgłasza na Pythonie 3.14 ostrzeżenie deprecacji `asyncio.iscoroutinefunction`. Testy przechodzą; ostrzeżenie pozostaje widoczne i dotyczy zależności pośredniej.

## Spec Kit for Codex

Official Spec Kit 1.4.1 was installed from the pinned GitHub tag. `make spec-check`
passes: the CLI version matches, the Codex integration is valid, all managed files
are present and match their manifests, all six Bash scripts pass syntax checks,
and template resolution and feature-creation dry runs work.

An isolated temporary directory was used to verify feature creation, persistence
of the current-feature pointer, plan preparation, task-template resolution, and
required-artifact checks. The fixture was removed; no test specification or
current-feature pointer was created in the repository.

Local Codex 0.169.0 discovered exactly nine project `speckit-*` skills through
`app-server` and a `skills/list` request. All were enabled, with no errors.
Verification did not invoke a model or change the global Codex configuration.
The default Makefile target remains `install`. Application code, runtime
dependencies, and deployment configuration were unchanged.

## Langfuse integration

Verified on November 17, 2026 against self-hosted Langfuse 4.82.0 with separate
PostgreSQL 18.7, ClickHouse 26.10.5.57, Redis 8.10.3 and RustFS 1.0.6. All twelve
long-running Compose services are healthy. Langfuse headless initialization and
S3 bucket creation completed successfully without modifying the application's
PostgreSQL data or schema.

`make langfuse-smoke` indexed a public source and queried it through the actual
Ollama/LangGraph pipeline. Public Observations API v2 returned five observations
for the supplied request ID: root, embedding, retrieval, graph and generation.
They share one trace ID, generation has the configured model, and all input/output
fields are null with default content capture disabled. The application submitted
public OTLP HTTP/JSON with the native v4 ingestion header. The original
`make ai-smoke` passed as well.

The final API suite passed with 332 tests and four optional PostgreSQL/graph-vector
integration cases skipped. Combined coverage with branch measurement is 97.28%.
Tests cover export failure and timeout, partial acceptance, content opt-in and
bounds, metadata filtering, exception-message privacy, concurrency isolation,
Vercel endpoint validation, and completion of export before the HTTP response
starts. Strict Ruff and Pyright pass. Twelve Playwright scenarios passed through
Compose across Chromium, Firefox, WebKit and mobile Chromium.

Vercel entrypoint import passed with the external Langfuse example configuration,
PostgreSQL NullPool, content capture disabled and a three-second export budget.
No Langfuse Cloud deployment, credentials or real Cloud request were provisioned.
No SDK, global tracer provider, automatic HTTP instrumentation or background
export worker was added to the application.

The constitution is now version 2.0.0: explicitly configured Langfuse AI
observability is allowed, replacing the earlier blanket telemetry prohibition.
Unrelated telemetry, dependency audits and GitHub Actions remain excluded.
`make spec-check` still reports unchanged upstream templates and valid integration.
The dedicated Langfuse skills were researched and documented, without installation.

## Official skills and MCP

Verified on November 18, 2026 with local Codex 0.169.0. Eleven additional
first-party skills were installed from full upstream commit SHAs, preserving the
original skill files and references. Licenses and source revisions are recorded
in `.agents/skills.lock.json`. Codex `app-server` discovered exactly 20 enabled
project skills: nine existing Spec Kit skills and eleven additions, with no loader
errors. This check used `skills/list` without starting a model or conversation.
The manifest paths, names, license files, and all ten auxiliary-file hashes match.

All four documentation MCP endpoints passed real HTTP `initialize` and
`tools/list` requests. Their configured allowlists contain only available read
tools and exclude feedback submission. GitHub authenticated through the existing
`gh` login and returned the 33 tools for the selected context, repository, and
pull-request toolsets. No GitHub data was changed.

Atlassian v2 OAuth login completed successfully. An authenticated app-server
`mcpServerStatus/list` request returned all 28 tools, including `discover`,
`executeRead`, and `executeWrite`, with no tool-catalog errors. This verification
did not call Jira or Confluence data tools or start a model or conversation.

Neo4j MCP 2.1.1 passed actual STDIO handshakes from the checkout root, `api/`,
and `web/`. Its catalog contains only `get-schema` and `read-cypher`, both marked
read-only. `RETURN 1 AS ok` and schema inspection passed; no write queries were
executed. The official server requires APOC at handshake time even when schema
tools are filtered. Compose now enables the bundled APOC Core jar with only
`apoc.meta.schema` allowed and unrestricted. MCP telemetry is disabled; the
local server also retains its disabled Bolt telemetry setting.

The stable Playwright 1.65.1 CLI opened the Compose frontend in an isolated
session, captured the text `Aplikacja działa.`, and closed the browser. Temporary
browser artifacts were removed. The official scoped Langfuse CLI 1.3.1 returned
HTTP 200 for local health and authenticated project-list requests without printing
credentials or project details. Five environment-mapping tests cover shell and
dotenv precedence, aliases, local ports, and remote credential fallbacks.

`make agent-install`, `make agent-check`, `make spec-check`, and all twelve local
pre-commit hooks passed. The Neo4j wrapper also passes Ruff lint and formatting.
All twelve long-running Compose services are healthy; migrations and initialization
jobs completed successfully. Application code and application dependency locks
were unchanged; agent CLI dependencies have separate locks.
