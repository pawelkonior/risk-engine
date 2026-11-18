# Application API

Gotowa baza backendu FastAPI do budowy aplikacji. Zachowuje strukturę templatki z Flashcard Pro: moduły funkcjonalne, konfigurację `APP_*`, logi JSON, obsługę błędów i rygorystyczne quality gates. Baza danych jest obowiązkowa: SQLite albo PostgreSQL. Wbudowane tracing, metryki, eksport logów i automatyczna konfiguracja telemetrii FastAPI są jawnie wyłączone. Sam pakiet `opentelemetry-api` jest wymaganą zależnością aktualnego FastAPI; nie instalujemy OpenTelemetry SDK ani automatycznych exporterów. Jawny adapter HTTP Langfuse eksportuje wybrane operacje AI, gdy jest włączony.

Wersje zależności przypięto do najnowszych stabilnych wydań dostępnych w PyPI 2026-11-17; `uv.lock` utrwala również zależności pośrednie. Python 3.14.10 to najnowszy patch linii obsługiwanej przez Vercel. Nowsza linia Python 3.15 nie jest jeszcze dostępna w jego runtime. [Wydania Python](https://www.python.org/downloads/), [runtime Vercel](https://vercel.com/docs/functions/runtimes/python).

## Szkielet AI

Backend zawiera LangGraph, adaptery HTTP Ollamy i chat API zgodnego z OpenAI, Neo4j dla dwóch połączonych grafów (wiedza + źródła) oraz Qdrant dla wyszukiwania wektorowego. SQL jest nadal obowiązkowy: `ai_index_records` przechowuje statusy i identyczność indeksowanych dokumentów.

AI jest domyślnie wyłączone przy samodzielnym uruchomieniu API. Root `make up` włącza je i inicjalizuje cały stos; `make ai-smoke` sprawdza rzeczywisty przepływ. `uv run python -m app.platform.ai.setup` jawnie tworzy constraints i indeksy, bez pobierania modeli i bez migracji SQL. Żaden request nie wykonuje DDL.

Przykład wdrożenia z zewnętrznymi usługami znajduje się w [.env.vercel.example](.env.vercel.example). [Dokumentacja AI](../docs/ai.md) opisuje kontrakty REST, ponawianie indeksowania, embeddingi i darmowe plany. LangSmith jest zależnością pośrednią LangGraph; tracing jest jawnie wyłączony także przy zmiennych tracingu w środowisku hosta. Sterownik Neo4j również ma wyłączoną telemetrię.

## Langfuse

Root Compose włącza lokalny Langfuse. Samodzielne API domyślnie ma
`APP_LANGFUSE_ENABLED=false`; po włączeniu wymaga adresu i obu kluczy projektu.
Ślady AI są wysyłane przez publiczny OTLP HTTP/JSON v4, bez SDK i globalnego
tracera. Eksport kończy się przed rozpoczęciem odpowiedzi HTTP, ma osobny limit
3 sekund i nie zmienia wyniku API przy awarii Langfuse. Treść promptów, źródeł
i odpowiedzi jest domyślnie wyłączona. [Pełna konfiguracja](../docs/langfuse.md).

## Uruchomienie lokalne — SQLite

Potrzebujesz Python 3.14.10 i [uv](https://docs.astral.sh/uv/).

```bash
cd api
cp .env.example .env
uv sync --all-groups --locked
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

API działa na `http://127.0.0.1:8000`, Swagger na `/docs`. Domyślnie dane trafiają do `api/app.db`. Kopiując sam katalog `api` do osobnego repozytorium, uruchamiaj polecenia bez pierwszego `cd api`.

```bash
curl http://127.0.0.1:8000/health/ready
curl -X POST http://127.0.0.1:8000/api/v1/items \
  -H 'Content-Type: application/json' \
  -d '{"title":"Pierwszy element","description":"Przykład modułu aplikacji"}'
curl 'http://127.0.0.1:8000/api/v1/items?limit=20&offset=0'
```

`items` jest publicznym przykładem CRUD do zastąpienia lub rozwinięcia. Nie zawiera logowania użytkowników ani uprawnień. Przed wykorzystaniem go do danych użytkowników dodaj uwierzytelnianie i filtrowanie po właścicielu. Klasy błędów 401/403 są gotowe, lecz nie stanowią implementacji auth.

## PostgreSQL

```bash
# Z katalogu api; uruchamia tylko lokalną bazę.
docker compose up -d postgres
```

W `.env` ustaw:

```dotenv
APP_DATABASE_URL=postgresql+psycopg://app:app-local-only@127.0.0.1:5432/app
APP_DATABASE_POOL_MODE=queue
```

Następnie uruchom `uv run alembic upgrade head` i serwer. Obsługiwane są też URL-e `postgresql://` i `postgres://`; konfiguracja normalizuje je do sterownika psycopg. `DATABASE_URL` jest aliasem `APP_DATABASE_URL` — ustawiaj jedną z tych zmiennych.

Cały zestaw kontenerów:

```bash
make -C .. up
```

Hasło z Compose służy wyłącznie lokalnemu środowisku. Kontener aplikacji działa bez roota. Domyślny standalone Docker używa `/app/data/app.db`; dla trwałego SQLite podłącz zapisywalny wolumen pod `/app/data` i uruchom w nim migracje. Compose używa trwałego wolumenu PostgreSQL.

## Vercel

Projekt korzysta z natywnej obsługi FastAPI i Python 3.14. `index.py` eksportuje `app`, a `pyproject.toml` wskazuje `tool.vercel.entrypoint = "index:app"`. `vercel.json` ustawia limit czasu funkcji na 60 sekund. Konfiguracja nie wymaga legacy builderów ani przepisywania tras. [Dokumentacja Python](https://vercel.com/docs/functions/runtimes/python), [FastAPI na Vercel](https://vercel.com/docs/frameworks/backend/fastapi).

1. Podłącz repozytorium w Vercel i ustaw **Root Directory: `api`**. Przy samodzielnym repo zawierającym zawartość `api` pozostaw root projektu.
2. Wybierz preset FastAPI, jeśli nie został wykryty automatycznie. Pozostaw domyślne komendy instalacji i budowania. Do deploymentu dołącz `uv.lock`.
3. Dodaj zmienne środowiskowe dla odpowiedniego środowiska:

```dotenv
APP_ENVIRONMENT=production
APP_DOCS_ENABLED=false
DATABASE_URL=postgresql://user:password@pooler.example.com:5432/app?sslmode=require
APP_DATABASE_POOL_MODE=null
APP_CORS_ALLOWED_ORIGINS=["https://twoj-frontend.example.com"]
APP_CORS_ALLOW_CREDENTIALS=false
```

4. Wybierz region funkcji blisko bazy. Zastosuj migracje oddzielnie, z zaufanej maszyny lub kontrolowanego kroku release, a następnie wykonaj deployment:

```bash
# Ustaw rzeczywisty DATABASE_URL poza historią powłoki, np. przez secret manager.
uv run alembic upgrade head
# CLI uruchamiaj z katalogu api.
vercel
```

Do migracji można ustawić `APP_DATABASE_MIGRATION_URL` (alias `DIRECT_DATABASE_URL`) z bezpośrednim adresem PostgreSQL, gdy runtime korzysta z transaction poolera. To ustawienie jest wykorzystywane tylko przez Alembic. Migracje nie uruchamiają się podczas importu, startupu ani builda. Preview powinno korzystać z osobnej bazy lub gałęzi bazy i własnych migracji.

SQLite służy lokalnemu developmentowi i serwerom z trwałym dyskiem. Na Vercel używaj hostowanego PostgreSQL: pliki `/tmp` nie są współdzielone i znikają wraz z instancją. Aplikacja odrzuca SQLite przy `VERCEL=1`. Dla transaction poolera używaj `null`: SQLAlchemy nie utrzymuje lokalnej puli, a psycopg wyłącza automatyczne prepared statements. [Trwałość plików Vercel](https://vercel.com/docs/functions/runtimes#file-system-support).

Deploy do Vercel wymaga własnego konta, repozytorium i danych dostępowych do bazy. Ten starter dostarcza konfigurację; samo utworzenie projektu nie publikuje aplikacji.

## Endpointy

| Metoda | Ścieżka                     | Zastosowanie                                      |
| ------ | --------------------------- | ------------------------------------------------- |
| GET    | `/health/live`              | Proces odpowiada                                  |
| GET    | `/health/ready`             | Zapytanie kontrolne do obowiązkowej bazy          |
| GET    | `/api/v1/status`            | Nazwa, wersja i środowisko usługi                 |
| GET    | `/api/v1/ai/status`         | Konfiguracja AI bez sekretów i prób połączenia    |
| PUT    | `/api/v1/ai/documents/{id}` | Idempotentne indeksowanie źródła i jawnych faktów |
| GET    | `/api/v1/ai/documents/{id}` | Status dokumentu w namespace i kolekcji           |
| POST   | `/api/v1/ai/query`          | Stateless LangGraph, źródła i fakty               |
| POST   | `/api/v1/items`             | Utworzenie elementu                               |
| GET    | `/api/v1/items`             | Lista z `limit` (maks. 100) i `offset`            |
| GET    | `/api/v1/items/{id}`        | Pobranie elementu                                 |
| PATCH  | `/api/v1/items/{id}`        | Częściowa aktualizacja                            |
| DELETE | `/api/v1/items/{id}`        | Usunięcie                                         |

Modele wejściowe odrzucają nieznane pola, a odpowiedzi błędów mają wspólną kopertę `error` z `code`, `message` i `request_id`. Logi dostępu zapisują wzorzec trasy zamiast surowej ścieżki URL i nie zapisują query stringów ani body. Nieoczekiwane błędy zapisują klasę wyjątku i bezpieczne ramki stosu, bez komunikatu wyjątku lub parametrów SQL. Limit body jest egzekwowany przed przekazaniem danych do handlera (domyślnie 1 MiB).

CORS domyślnie nie pozwala na żadne zewnętrzne originy; skonfiguruj konkretne adresy frontendu.

## Quality gates

```bash
make check
# lub osobno:
uv run ruff check
uv run ruff format --check
uv run pyright
uv run pytest
uv run --group docs sphinx-build -E -a -W --keep-going -b html docs docs/_build/html
uv run alembic check
```

`make check` instaluje zależności z locka i uruchamia tox: Ruff, formatter, strict Pyright, pytest z coverage co najmniej 90% z pomiarem gałęzi oraz Sphinx z ostrzeżeniami jako błędami. `alembic check` wykonuj po migracji bazy. Testy SQLite nie potrzebują Dockera. Dodatkowe testy PostgreSQL uruchamiają się po ustawieniu `TEST_DATABASE_URL` wskazującego **osobną testową bazę**, której schemat testy mogą zmieniać.

Lokalne hooki pre-commit uruchamiają pełny zestaw sprawdzeń: Ruff, kontrolę formatu, strict Pyright, pytest z wymaganym coverage i Sphinx z ostrzeżeniami jako błędami. Hooki sprawdzają kod i nie wprowadzają automatycznych poprawek.

Po utworzeniu repozytorium Git zainstaluj hooki z katalogu głównego tego projektu:

```bash
uv run --project api pre-commit install
uv run --project api pre-commit run --all-files
```

Konfiguracja w root obsługuje backend w katalogu `api`. Po skopiowaniu zawartości `api` do osobnego repozytorium korzystaj z dołączonej tam konfiguracji i poleceń:

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

Obie konfiguracje korzystają z lokalnych narzędzi projektu. `make format` służy do świadomego formatowania i automatycznych poprawek; hooki pozostają kontrolą jakości przy commitowaniu.

## Rozbudowa

Dodaj moduł pod `src/app/modules/<nazwa>` z modelami, schematami, service i routerem. Zarejestruj router w `http/router.py`, a model w metadanych migracji. Potem utwórz i sprawdź rewizję:

```bash
uv run alembic revision --autogenerate -m "add feature"
uv run alembic upgrade head
uv run alembic check
make check
```

Serwis zawiera zapytania i logikę przypadku użycia, zarządza transakcją i jawnie zatwierdza zapis. Nie zależy od FastAPI. Przy bardziej rozbudowanych zapytaniach można wydzielić repository. Każde żądanie dostaje osobną sesję z rollbackiem po błędzie. Nie uruchamiaj długich zadań ani cyklicznych workerów wewnątrz procesu obsługującego żądania serverless.

Opis decyzji i porównanie z szablonem Flashcard Pro znajdziesz w `docs/architecture.rst`, a instrukcje eksploatacji w `docs/operations.rst`.

## Testy z prawdziwymi bazami

Domyślny pytest używa izolowanego SQLite i mocków usług AI. Dodatkowe testy Neo4j/Qdrant wymagają lokalnych usług z Compose i `AI_INTEGRATION=1`. Test migracji PostgreSQL wykonuje downgrade, więc wymaga osobnej bazy o nazwie zaczynającej się od `test_`:

```bash
# Z root repozytorium, jednorazowo:
docker compose exec postgres createdb -U app test_template_ai
cd api
AI_INTEGRATION=1 \
TEST_DATABASE_URL=postgresql+psycopg://app:app-local-only@127.0.0.1:5432/test_template_ai \
uv run pytest
# Po testach, z root repozytorium:
docker compose exec postgres dropdb -U app test_template_ai
```

Podaj własne lokalne dane logowania, jeśli zmieniłeś konfigurację Compose. Rejestr aplikacji i baza testowa muszą być rozdzielone. Testy adapterów AI tworzą unikalne namespace’y i kolekcje oraz je sprzątają.
