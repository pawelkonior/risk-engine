from ipaddress import ip_address
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator

from app.core.settings.base import ComponentSettings


def _url(value: str, schemes: set[str]) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in schemes or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("service URL requires a supported scheme, host, and separate credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("service URL must not contain query parameters or a fragment")
    return value.rstrip("/")


def _external(value: str) -> bool:
    hostname = urlsplit(value).hostname or ""
    if hostname.lower() in {"localhost", "ollama", "qdrant", "neo4j", "host.docker.internal"}:
        return False
    try:
        return ip_address(hostname).is_global
    except ValueError:
        return "." in hostname


class AISettings(ComponentSettings):
    """Ollama by default; external services are configured explicitly for Vercel."""

    ai_enabled: bool = False
    ai_chat_provider: Literal["ollama", "openai_compatible"] = "ollama"
    ai_chat_model: str = Field(default="qwen3:0.6b", min_length=1, max_length=160)
    ai_ollama_base_url: str = "http://127.0.0.1:11434"
    ai_chat_base_url: str | None = None
    ai_chat_api_key: SecretStr | None = None
    ai_embedding_provider: Literal["ollama", "qdrant_cloud"] = "ollama"
    ai_embedding_model: str = Field(default="embeddinggemma", min_length=1, max_length=160)
    ai_embedding_dimensions: int = Field(default=768, ge=1, le=4096)
    ai_qdrant_url: str = "http://127.0.0.1:6333"
    ai_qdrant_api_key: SecretStr | None = None
    ai_qdrant_collection: str = Field(
        default="app_chunks_ollama_v1", pattern=r"^[A-Za-z0-9_-]{1,100}$"
    )
    ai_neo4j_uri: str = "bolt://127.0.0.1:7687"
    ai_neo4j_username: str = Field(default="neo4j", min_length=1, max_length=100)
    ai_neo4j_password: SecretStr = SecretStr("neo4j-local-only")
    ai_neo4j_database: str = Field(default="neo4j", min_length=1, max_length=100)
    ai_http_timeout_seconds: float = Field(default=40, gt=0, le=45)
    ai_request_timeout_seconds: float = Field(default=45, gt=0, le=50)

    @field_validator("ai_chat_api_key", "ai_qdrant_api_key", "ai_neo4j_password")
    @classmethod
    def nonempty_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().strip():
            raise ValueError("service credentials must not be empty")
        return value

    @field_validator(
        "ai_chat_model", "ai_embedding_model", "ai_neo4j_username", "ai_neo4j_database"
    )
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("service names must not be blank")
        return value

    @field_validator("ai_ollama_base_url", "ai_qdrant_url", "ai_chat_base_url")
    @classmethod
    def http_url(cls, value: str | None) -> str | None:
        return None if value is None else _url(value, {"http", "https"})

    @field_validator("ai_neo4j_uri")
    @classmethod
    def graph_url(cls, value: str) -> str:
        return _url(value, {"bolt", "bolt+s", "neo4j", "neo4j+s"})

    @model_validator(mode="after")
    def configured_providers(self) -> Self:
        if self.ai_chat_provider == "openai_compatible" and (
            self.ai_chat_base_url is None or self.ai_chat_api_key is None
        ):
            raise ValueError("OpenAI-compatible chat requires a base URL and API key")
        if self.ai_embedding_provider == "qdrant_cloud" and self.ai_qdrant_api_key is None:
            raise ValueError("Qdrant Cloud inference requires an API key")
        return self

    def validate_vercel(self) -> None:
        """Reject configurations that cannot work from a remote function."""
        if not self.ai_enabled:
            return
        if not self.ai_qdrant_url.startswith("https://") or not _external(self.ai_qdrant_url):
            raise ValueError("Vercel AI requires an external HTTPS Qdrant endpoint")
        if not self.ai_neo4j_uri.startswith(("neo4j+s://", "bolt+s://")) or not _external(
            self.ai_neo4j_uri
        ):
            raise ValueError("Vercel AI requires an external TLS Neo4j endpoint")
        if self.ai_neo4j_password.get_secret_value() == "neo4j-local-only":
            raise ValueError("Vercel AI requires configured graph database credentials")
        model_urls: list[str] = []
        if self.ai_chat_provider == "ollama" or self.ai_embedding_provider == "ollama":
            model_urls.append(self.ai_ollama_base_url)
        if self.ai_chat_base_url is not None:
            model_urls.append(self.ai_chat_base_url)
        if any(not value.startswith("https://") or not _external(value) for value in model_urls):
            raise ValueError("Vercel AI requires external HTTPS model endpoints")

    @property
    def embedding_profile(self) -> str:
        return (
            f"{self.ai_embedding_provider}:{self.ai_embedding_model}:{self.ai_embedding_dimensions}"
        )
