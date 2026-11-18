import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch

from app.core.config import DatabaseSettings
from app.core.settings.database import normalize_database_url

_SECRET = "DATABASE_SECRET_MUST_NOT_APPEAR"
_POSTGRES_URL = f"postgresql://app:{_SECRET}@localhost:5432/application"


def test_database_is_required_with_sqlite_default() -> None:
    settings = DatabaseSettings(_env_file=None)
    assert settings.database_url.get_secret_value() == "sqlite+aiosqlite:///./app.db"
    assert settings.is_sqlite
    assert settings.migration_url == settings.database_url.get_secret_value()


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg"])
def test_postgres_urls_are_normalized(scheme: str) -> None:
    url = normalize_database_url(
        f"{scheme}://user:password@localhost:5432/application?sslmode=require"
    )
    assert url == "postgresql+psycopg://user:password@localhost:5432/application?sslmode=require"


@pytest.mark.parametrize("url", ["sqlite:///./local.db", "sqlite+aiosqlite:///:memory:"])
def test_sqlite_urls_are_normalized(url: str) -> None:
    assert normalize_database_url(url).startswith("sqlite+aiosqlite:///")


@pytest.mark.parametrize(
    "url",
    [
        "not-a-dsn-" + _SECRET,
        "mysql://user:password@localhost/app",
        "postgresql+asyncpg://user:password@localhost/app",
        "postgresql:///app",
        "postgresql://localhost",
        "sqlite://remote/file.db",
        "sqlite://",
        "postgresql://localhost:invalid/app",
    ],
)
def test_invalid_database_urls_hide_credentials(url: str) -> None:
    with pytest.raises(ValidationError) as error:
        DatabaseSettings(_env_file=None, database_url=url)
    assert _SECRET not in str(error.value)


def test_database_aliases_and_secret_redaction(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", _POSTGRES_URL)
    monkeypatch.setenv("DIRECT_DATABASE_URL", _POSTGRES_URL.replace("localhost", "direct"))
    settings = DatabaseSettings(_env_file=None)
    assert settings.database_url.get_secret_value().startswith("postgresql+psycopg://")
    assert "@direct" in settings.migration_url
    assert not settings.is_sqlite
    assert _SECRET not in repr(settings)
    monkeypatch.setenv("APP_DATABASE_URL", "sqlite:///./override.db")
    assert DatabaseSettings(_env_file=None).is_sqlite


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("database_pool_size", 0),
        ("database_pool_size", 51),
        ("database_max_overflow", -1),
        ("database_max_overflow", 51),
        ("database_pool_timeout_seconds", 0),
        ("database_connect_timeout_seconds", 0),
        ("database_pool_mode", "invalid"),
    ],
)
def test_invalid_database_settings(name: str, value: object) -> None:
    with pytest.raises(ValidationError):
        DatabaseSettings(_env_file=None, **{name: value})
