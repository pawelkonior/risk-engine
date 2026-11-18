from typing import Any, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.core.settings.base import DEFAULT_ENV_FILE, ComponentSettings


def normalize_database_url(value: str) -> str:
    """Accept only SQLite and PostgreSQL, using the supported async drivers."""
    try:
        url = make_url(value)
    except ArgumentError, ValueError:
        raise ValueError("database URL must be a valid PostgreSQL or SQLite URL") from None
    if url.drivername in {"postgres", "postgresql", "postgresql+psycopg"}:
        if not url.host or not url.database:
            raise ValueError("PostgreSQL URL requires a host and database name")
        url = url.set(drivername="postgresql+psycopg")
    elif url.drivername in {"sqlite", "sqlite+aiosqlite"}:
        if url.host or url.username or not url.database:
            raise ValueError("SQLite URL requires a file path or :memory:")
        url = url.set(drivername="sqlite+aiosqlite")
    else:
        raise ValueError("database URL must use PostgreSQL (psycopg) or SQLite (aiosqlite)")
    return url.render_as_string(hide_password=False)


class DatabaseSettings(ComponentSettings):
    """Required persistence, with a local SQLite default and hosted PostgreSQL support."""

    model_config = SettingsConfigDict(hide_input_in_errors=True)

    database_url: SecretStr = Field(
        default=SecretStr("sqlite+aiosqlite:///./app.db"),
        validation_alias=AliasChoices("APP_DATABASE_URL", "DATABASE_URL"),
    )
    database_migration_url: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("APP_DATABASE_MIGRATION_URL", "DIRECT_DATABASE_URL"),
    )
    database_pool_mode: Literal["queue", "null"] = "queue"
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=5, ge=0, le=50)
    database_pool_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)

    def __init__(self, _env_file: Any = DEFAULT_ENV_FILE, **data: Any) -> None:
        super().__init__(_env_file=_env_file, **data)  # pyright: ignore[reportCallIssue]

    @field_validator("database_url", "database_migration_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        """Normalize supported URLs without reflecting database credentials in errors."""
        if value is None:
            return None
        return SecretStr(normalize_database_url(value.get_secret_value()))

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.get_secret_value().startswith("sqlite+")

    @property
    def migration_url(self) -> str:
        """Prefer a direct database connection for migration DDL."""
        return (self.database_migration_url or self.database_url).get_secret_value()
