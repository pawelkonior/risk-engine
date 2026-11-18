from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError
from pytest import MonkeyPatch

from app.core.config import Settings
from app.core.settings.langfuse import LangfuseSettings

_PUBLIC_KEY = "pk-lf-settings-secret-must-not-appear"
_SECRET_KEY = "sk-lf-settings-secret-must-not-appear"


def configured(**overrides: object) -> LangfuseSettings:
    values: dict[str, object] = {
        "langfuse_enabled": True,
        "langfuse_base_url": "https://cloud.langfuse.com",
        "langfuse_public_key": SecretStr(_PUBLIC_KEY),
        "langfuse_secret_key": SecretStr(_SECRET_KEY),
    }
    return Settings(_env_file=None, **(values | overrides)).langfuse


def test_default_observability_is_disabled_and_does_not_capture_content() -> None:
    settings = Settings(_env_file=None).langfuse
    assert not settings.langfuse_enabled
    assert not settings.langfuse_capture_content
    assert settings.langfuse_base_url == "http://127.0.0.1:3000"
    assert settings.langfuse_public_key is settings.langfuse_secret_key is None
    assert settings.langfuse_timeout_seconds == 3
    settings.validate_vercel()


@pytest.mark.parametrize(
    "credentials",
    [
        {},
        {"langfuse_public_key": SecretStr(_PUBLIC_KEY)},
        {"langfuse_secret_key": SecretStr(_SECRET_KEY)},
    ],
)
def test_enabled_observability_requires_both_credentials(credentials: dict[str, SecretStr]) -> None:
    with pytest.raises(ValidationError, match="requires a public key and a secret key") as error:
        Settings(_env_file=None, langfuse_enabled=True, **credentials)
    assert _PUBLIC_KEY not in str(error.value)
    assert _SECRET_KEY not in str(error.value)


@pytest.mark.parametrize("field", ["langfuse_public_key", "langfuse_secret_key"])
@pytest.mark.parametrize("value", ["", " \t"])
def test_blank_credentials_are_rejected_even_when_export_is_disabled(
    field: str, value: str
) -> None:
    with pytest.raises(ValidationError, match="credentials must not be blank"):
        Settings(_env_file=None, **{field: SecretStr(value)})


def test_disabled_observability_accepts_explicitly_unset_credentials() -> None:
    settings = Settings(_env_file=None, langfuse_public_key=None, langfuse_secret_key=None).langfuse
    assert settings.langfuse_public_key is settings.langfuse_secret_key is None


def test_credentials_are_hidden_from_settings_repr_and_json() -> None:
    settings = configured()
    assert settings.langfuse_public_key is not None
    assert settings.langfuse_secret_key is not None
    assert settings.langfuse_public_key.get_secret_value() == _PUBLIC_KEY
    assert settings.langfuse_secret_key.get_secret_value() == _SECRET_KEY
    for rendered in (str(settings), repr(settings), settings.model_dump_json()):
        assert _PUBLIC_KEY not in rendered
        assert _SECRET_KEY not in rendered


@pytest.mark.parametrize(
    "value",
    [
        "ftp://cloud.langfuse.com",
        "https://",
        "https://cloud.langfuse.com:not-a-port",
        "https://cloud.langfuse.com:70000",
        f"https://user:{_SECRET_KEY}@cloud.langfuse.com",
        f"https://{_PUBLIC_KEY}@cloud.langfuse.com",
        f"https://cloud.langfuse.com?key={_SECRET_KEY}",
        f"https://cloud.langfuse.com#{_SECRET_KEY}",
    ],
)
def test_endpoint_rejects_unsupported_urls_and_embedded_credentials(value: str) -> None:
    with pytest.raises(ValidationError, match=r"HTTP\(S\) URL") as error:
        Settings(_env_file=None, langfuse_base_url=value)
    assert _PUBLIC_KEY not in str(error.value)
    assert _SECRET_KEY not in str(error.value)


def test_endpoint_normalizes_trailing_slashes_and_preserves_base_path() -> None:
    settings = configured(langfuse_base_url="https://observability.example.com/langfuse/")
    assert settings.langfuse_base_url == "https://observability.example.com/langfuse"


@pytest.mark.parametrize("deadline", [0, -1, 5.1])
def test_export_timeout_cannot_be_zero_or_exceed_the_request_budget(deadline: float) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, langfuse_timeout_seconds=deadline)


def test_flat_environment_contract_loads_known_fields_and_hides_secrets(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("APP_LANGFUSE_BASE_URL", "https://cloud.langfuse.com/")
    monkeypatch.setenv("APP_LANGFUSE_PUBLIC_KEY", _PUBLIC_KEY)
    monkeypatch.setenv("APP_LANGFUSE_SECRET_KEY", _SECRET_KEY)
    monkeypatch.setenv("APP_LANGFUSE_CAPTURE_CONTENT", "true")
    monkeypatch.setenv("APP_LANGFUSE_TIMEOUT_SECONDS", "2")
    settings = Settings(_env_file=None)
    assert settings.langfuse.langfuse_enabled
    assert settings.langfuse.langfuse_capture_content
    assert settings.langfuse.langfuse_base_url == "https://cloud.langfuse.com"
    assert settings.langfuse.langfuse_timeout_seconds == 2
    assert _PUBLIC_KEY not in repr(settings)
    assert _SECRET_KEY not in settings.model_dump_json()


def test_misspelled_environment_setting_is_rejected(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("APP_LANGFUSE_ENABELD", "true")
    with pytest.raises(ValueError, match="APP_LANGFUSE_ENABELD"):
        Settings(_env_file=None)


def test_misspelled_dotenv_setting_is_rejected(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("APP_LANGFUSE_CAPTURE_CONTNET=true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="APP_LANGFUSE_CAPTURE_CONTNET"):
        Settings(_env_file=dotenv)


def test_nested_and_flat_observability_overrides_cannot_be_combined() -> None:
    with pytest.raises(ValueError, match="nested langfuse settings with flat overrides"):
        Settings(_env_file=None, langfuse=configured(), langfuse_capture_content=True)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://cloud.langfuse.com",
        "https://us.cloud.langfuse.com",
        "https://jp.cloud.langfuse.com",
        "https://observability.example.com",
        "https://8.8.8.8",
    ],
)
def test_vercel_accepts_external_https_with_project_credentials(endpoint: str) -> None:
    configured(langfuse_base_url=endpoint).validate_vercel()


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://cloud.langfuse.com",
        "https://localhost",
        "https://localhost.",
        "https://127.0.0.1",
        "https://127.1",
        "https://0x7f.0.0.1",
        "https://10.1.2.3",
        "https://[::1]",
        "https://langfuse-web",
        "https://host.docker.internal",
        "https://host.docker.internal.",
        "https://host.docker.internal。",
        "https://observability.localhost",
        "https://observability.local",
        "https://observability.local.",
        "https://observability.internal",
        "https://observability.internal.",
    ],
)
def test_vercel_rejects_local_or_unencrypted_observability(endpoint: str) -> None:
    with pytest.raises(ValueError, match="external HTTPS Langfuse endpoint"):
        configured(langfuse_base_url=endpoint).validate_vercel()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("langfuse_public_key", "pk-lf-template-local"),
        ("langfuse_secret_key", "sk-lf-template-local"),
    ],
)
def test_vercel_rejects_local_template_credentials(field: str, value: str) -> None:
    with pytest.raises(ValueError, match="configured Langfuse project credentials"):
        configured(**{field: SecretStr(value)}).validate_vercel()


def test_vercel_root_settings_enforce_observability_endpoint_validation() -> None:
    with pytest.raises(ValidationError, match="external HTTPS Langfuse endpoint"):
        Settings(
            _env_file=None,
            vercel=True,
            docs_enabled=False,
            database_url="postgresql+psycopg://user:password@db.example.com/app",
            langfuse_enabled=True,
            langfuse_public_key=SecretStr(_PUBLIC_KEY),
            langfuse_secret_key=SecretStr(_SECRET_KEY),
        )
