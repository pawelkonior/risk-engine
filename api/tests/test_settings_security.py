import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch
from sqlalchemy.engine import make_url

from app.core.config import Environment, Settings

_POSTGRES_URL = "postgresql://application:deployment-canary@db.example/application"


def test_vercel_rejects_ephemeral_sqlite_database(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("VERCEL", "1")

    with pytest.raises(ValidationError, match="Vercel requires PostgreSQL"):
        Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:")


@pytest.mark.parametrize(
    ("vercel_environment", "expected_environment"),
    [("preview", Environment.STAGING), ("production", Environment.PRODUCTION)],
)
def test_vercel_uses_postgres_without_retaining_connection_pool(
    monkeypatch: MonkeyPatch,
    vercel_environment: str,
    expected_environment: Environment,
) -> None:
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_ENV", vercel_environment)

    settings = Settings(
        _env_file=None,
        database_url=_POSTGRES_URL,
        database_pool_mode="queue",
        docs_enabled=False,
    )

    assert settings.runtime.vercel is True
    assert settings.runtime.environment is expected_environment
    assert settings.database.database_pool_mode == "null"
    assert settings.database.is_sqlite is False
    assert "deployment-canary" not in repr(settings)


def test_vercel_production_applies_documentation_gate(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_ENV", "production")

    with pytest.raises(ValidationError, match="documentation must be disabled"):
        Settings(_env_file=None, database_url=_POSTGRES_URL, docs_enabled=True)


def test_explicit_app_database_url_wins_over_platform_alias(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://platform:alias@db.example/ignored")
    monkeypatch.setenv("APP_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

    settings = Settings(_env_file=None)

    url = make_url(settings.database.database_url.get_secret_value())
    assert url.drivername == "sqlite+aiosqlite"
    assert url.database == ":memory:"
