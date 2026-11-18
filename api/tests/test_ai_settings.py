import pytest
from pydantic import SecretStr, ValidationError
from pytest import MonkeyPatch

from app.core.config import Settings
from app.core.settings.ai import AISettings

_SECRET = "AI_SETTINGS_SECRET_MUST_NOT_APPEAR"


def test_local_defaults_are_disabled_and_use_ollama() -> None:
    settings = Settings(_env_file=None).ai
    assert not settings.ai_enabled
    assert settings.ai_chat_provider == settings.ai_embedding_provider == "ollama"
    assert settings.ai_chat_model == "qwen3:0.6b"
    assert settings.ai_embedding_model == "embeddinggemma"
    assert settings.ai_embedding_dimensions == 768
    assert settings.embedding_profile == "ollama:embeddinggemma:768"
    settings.validate_vercel()


def test_environment_contract_loads_secrets_without_exposing_them(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("APP_AI_ENABLED", "true")
    monkeypatch.setenv("APP_AI_QDRANT_API_KEY", _SECRET)
    monkeypatch.setenv("APP_AI_CHAT_API_KEY", _SECRET)
    monkeypatch.setenv("APP_AI_NEO4J_PASSWORD", _SECRET)
    settings = Settings(_env_file=None)
    assert settings.ai.ai_enabled
    assert settings.ai.ai_chat_api_key is not None
    assert settings.ai.ai_chat_api_key.get_secret_value() == _SECRET
    assert settings.ai.ai_neo4j_password.get_secret_value() == _SECRET
    assert _SECRET not in repr(settings)
    assert _SECRET not in settings.model_dump_json()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ai_ollama_base_url", "ftp://models.example.com"),
        ("ai_qdrant_url", "https://user:secret@vectors.example.com"),
        ("ai_chat_base_url", "https://models.example.com?token=secret"),
        ("ai_chat_base_url", "https://models.example.com#secret"),
        ("ai_neo4j_uri", "neo4j+s://user:secret@graph.example.com"),
        ("ai_neo4j_uri", "http://graph.example.com"),
        ("ai_neo4j_uri", "bolt://"),
    ],
)
def test_service_urls_reject_embedded_credentials_or_unsupported_forms(
    field: str, value: str
) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_service_base_urls_are_normalized_without_modifying_paths() -> None:
    settings = Settings(
        _env_file=None,
        ai_ollama_base_url="https://models.example.com/",
        ai_qdrant_url="https://vectors.example.com/",
        ai_neo4j_uri="neo4j+s://graph.example.com/",
        ai_chat_base_url="https://models.example.com/account/ai/v1/",
    ).ai
    assert settings.ai_ollama_base_url == "https://models.example.com"
    assert settings.ai_qdrant_url == "https://vectors.example.com"
    assert settings.ai_neo4j_uri == "neo4j+s://graph.example.com"
    assert settings.ai_chat_base_url == "https://models.example.com/account/ai/v1"


@pytest.mark.parametrize(
    "overrides",
    [
        {"ai_chat_provider": "openai_compatible"},
        {"ai_chat_provider": "openai_compatible", "ai_chat_base_url": "https://chat.example.com"},
        {"ai_chat_provider": "openai_compatible", "ai_chat_api_key": SecretStr(_SECRET)},
        {"ai_embedding_provider": "qdrant_cloud"},
    ],
)
def test_cloud_providers_require_explicit_credentials(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, **overrides)
    assert _SECRET not in str(error.value)


@pytest.mark.parametrize("field", ["ai_chat_api_key", "ai_qdrant_api_key", "ai_neo4j_password"])
@pytest.mark.parametrize("value", ["", " \t"])
def test_empty_or_whitespace_credentials_are_rejected(field: str, value: str) -> None:
    with pytest.raises(ValidationError, match="credentials must not be empty"):
        Settings(_env_file=None, **{field: SecretStr(value)})


@pytest.mark.parametrize(
    "field", ["ai_chat_model", "ai_embedding_model", "ai_neo4j_username", "ai_neo4j_database"]
)
def test_blank_service_names_are_rejected(field: str) -> None:
    with pytest.raises(ValidationError, match="names must not be blank"):
        Settings(_env_file=None, **{field: " \t"})
    assert getattr(Settings(_env_file=None, **{field: "custom"}).ai, field) == "custom"


def test_optional_credentials_can_remain_unset_for_local_ollama() -> None:
    settings = Settings(_env_file=None, ai_chat_api_key=None, ai_qdrant_api_key=None).ai
    assert settings.ai_chat_api_key is settings.ai_qdrant_api_key is None


def cloud_settings(**overrides: object) -> AISettings:
    values: dict[str, object] = {
        "ai_enabled": True,
        "ai_chat_provider": "openai_compatible",
        "ai_chat_base_url": "https://models.example.com/account/ai/v1",
        "ai_chat_api_key": SecretStr(_SECRET),
        "ai_embedding_provider": "qdrant_cloud",
        "ai_embedding_model": "intfloat/multilingual-e5-small",
        "ai_embedding_dimensions": 384,
        "ai_qdrant_url": "https://vectors.example.com",
        "ai_qdrant_api_key": SecretStr(_SECRET),
        "ai_neo4j_uri": "neo4j+s://graph.example.com",
        "ai_neo4j_password": SecretStr(_SECRET),
    }
    return Settings(_env_file=None, **(values | overrides)).ai


def test_vercel_accepts_external_tls_services_and_no_local_models() -> None:
    settings = cloud_settings()
    settings.validate_vercel()
    assert settings.embedding_profile == "qdrant_cloud:intfloat/multilingual-e5-small:384"
    cloud_settings(ai_neo4j_uri="bolt+s://graph.example.com").validate_vercel()
    cloud_settings(
        ai_chat_provider="ollama",
        ai_embedding_provider="ollama",
        ai_ollama_base_url="https://ollama.example.com",
        ai_chat_base_url=None,
    ).validate_vercel()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"ai_qdrant_url": "http://vectors.example.com"}, "HTTPS Qdrant"),
        ({"ai_qdrant_url": "https://localhost"}, "HTTPS Qdrant"),
        ({"ai_qdrant_url": "https://127.0.0.1"}, "HTTPS Qdrant"),
        ({"ai_qdrant_url": "https://10.0.0.1"}, "HTTPS Qdrant"),
        ({"ai_qdrant_url": "https://[::1]"}, "HTTPS Qdrant"),
        ({"ai_qdrant_url": "https://qdrant"}, "HTTPS Qdrant"),
        ({"ai_qdrant_url": "https://internal"}, "HTTPS Qdrant"),
        ({"ai_neo4j_uri": "bolt://graph.example.com"}, "TLS Neo4j"),
        ({"ai_neo4j_uri": "neo4j+s://neo4j"}, "TLS Neo4j"),
        ({"ai_neo4j_password": SecretStr("neo4j-local-only")}, "graph database credentials"),
        ({"ai_chat_base_url": "http://models.example.com"}, "HTTPS model"),
        ({"ai_chat_base_url": "https://host.docker.internal"}, "HTTPS model"),
        ({"ai_embedding_provider": "ollama"}, "HTTPS model"),
        ({"ai_chat_provider": "ollama"}, "HTTPS model"),
    ],
)
def test_vercel_rejects_local_or_unencrypted_dependencies(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        cloud_settings(**overrides).validate_vercel()


def test_vercel_root_settings_enforce_ai_validation() -> None:
    with pytest.raises(ValidationError, match="external HTTPS Qdrant"):
        Settings(
            _env_file=None,
            vercel=True,
            ai_enabled=True,
            database_url="postgresql+psycopg://user:password@db.example.com/app",
        )
