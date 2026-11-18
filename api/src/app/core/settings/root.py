from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.core.settings.ai import AISettings
from app.core.settings.base import (
    DEFAULT_ENV_FILE,
    Environment,
    component_source_kwargs,
    known_environment_names,
    reject_unknown_app_dotenv,
    reject_unknown_app_environment,
)
from app.core.settings.database import DatabaseSettings
from app.core.settings.langfuse import LangfuseSettings
from app.core.settings.runtime import HttpSettings, RuntimeSettings

_COMPONENT_TYPES = {
    "ai": AISettings,
    "langfuse": LangfuseSettings,
    "runtime": RuntimeSettings,
    "http": HttpSettings,
    "database": DatabaseSettings,
}
_KNOWN_ENVIRONMENT_NAMES = known_environment_names(*_COMPONENT_TYPES.values())


class Settings(BaseModel):
    """Validated, component-oriented application configuration."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    ai: AISettings
    langfuse: LangfuseSettings
    runtime: RuntimeSettings
    http: HttpSettings
    database: DatabaseSettings

    def __init__(self, _env_file: Any = DEFAULT_ENV_FILE, **data: Any) -> None:
        reject_unknown_app_environment(_KNOWN_ENVIRONMENT_NAMES)
        reject_unknown_app_dotenv(_KNOWN_ENVIRONMENT_NAMES, _env_file)
        component_overrides: dict[str, dict[str, Any]] = {name: {} for name in _COMPONENT_TYPES}
        for key in tuple(data):
            matches = [
                name
                for name, component_type in _COMPONENT_TYPES.items()
                if key in component_type.model_fields
            ]
            if len(matches) == 1:
                component_overrides[matches[0]][key] = data.pop(key)

        source_kwargs = component_source_kwargs(_env_file)
        for name, component_type in _COMPONENT_TYPES.items():
            overrides = component_overrides[name]
            if name in data and overrides:
                raise ValueError(f"cannot combine nested {name} settings with flat overrides")
            if name not in data:
                data[name] = component_type(
                    **source_kwargs,
                    **overrides,
                )  # pyright: ignore[reportCallIssue]
        super().__init__(**data)

    @model_validator(mode="after")
    def validate_environment_safety(self) -> Self:
        if self.runtime.vercel:
            self.ai.validate_vercel()
            self.langfuse.validate_vercel()
            if self.database.database_url.get_secret_value().startswith("sqlite"):
                raise ValueError("Vercel requires PostgreSQL; SQLite files are not persistent")
            self.database = self.database.model_copy(update={"database_pool_mode": "null"})
            if self.runtime.environment is Environment.LOCAL:
                environment = (
                    Environment.PRODUCTION
                    if os.environ.get("VERCEL_ENV") == "production"
                    else Environment.STAGING
                )
                self.runtime = self.runtime.model_copy(update={"environment": environment})
        if self.runtime.environment is Environment.PRODUCTION and self.http.docs_enabled:
            raise ValueError("API documentation must be disabled in production")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide validated settings instance."""
    return Settings()
