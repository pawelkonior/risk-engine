import re
from contextlib import suppress
from ipaddress import ip_address
from typing import Self
from urllib.parse import urlsplit

import httpx
from pydantic import Field, SecretStr, field_validator, model_validator

from app.core.settings.base import ComponentSettings


class LangfuseSettings(ComponentSettings):
    """Explicit AI observability, independent of platform usage telemetry."""

    langfuse_enabled: bool = False
    langfuse_base_url: str = "http://127.0.0.1:3000"
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_capture_content: bool = False
    langfuse_timeout_seconds: float = Field(default=3, gt=0, le=5)

    @field_validator("langfuse_base_url")
    @classmethod
    def http_url(cls, value: str) -> str:
        message = "Langfuse requires an HTTP(S) URL with separate credentials"
        try:
            normalized = str(httpx.URL(value))
            parsed = urlsplit(normalized)
            _ = parsed.port
        except httpx.InvalidURL, ValueError:
            raise ValueError(message) from None
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(message)
        return normalized.rstrip("/")

    @field_validator("langfuse_public_key", "langfuse_secret_key")
    @classmethod
    def nonempty_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().strip():
            raise ValueError("Langfuse credentials must not be blank")
        return value

    @model_validator(mode="after")
    def configured_credentials(self) -> Self:
        if self.langfuse_enabled and (
            self.langfuse_public_key is None or self.langfuse_secret_key is None
        ):
            raise ValueError("Enabled Langfuse requires a public key and a secret key")
        return self

    def validate_vercel(self) -> None:
        if not self.langfuse_enabled:
            return
        parsed = urlsplit(self.langfuse_base_url)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        external = "." in hostname and hostname not in {"host.docker.internal"}
        if all(
            part.isdecimal() or re.fullmatch(r"0x[0-9a-f]+", part) for part in hostname.split(".")
        ):
            external = False
        with suppress(ValueError):
            external = ip_address(hostname).is_global
        if (
            parsed.scheme != "https"
            or not external
            or hostname.endswith((".local", ".internal", ".localhost"))
        ):
            raise ValueError("Vercel requires an external HTTPS Langfuse endpoint")
        for key in (self.langfuse_public_key, self.langfuse_secret_key):
            if key is not None and key.get_secret_value() in {
                "pk-lf-template-local",
                "sk-lf-template-local",
            }:
                raise ValueError("Vercel requires configured Langfuse project credentials")
