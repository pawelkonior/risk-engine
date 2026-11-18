from collections.abc import Iterator
from unittest.mock import Mock

import pytest
from pytest import MonkeyPatch

from app import main
from app.core.config import Environment, Settings, get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    """Prevent process-wide settings from leaking between tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def test_settings() -> Settings:
    """Return isolated settings without reading a local dotenv file."""
    return Settings(
        _env_file=None,
        environment=Environment.TEST,
        docs_enabled=True,
        database_url="sqlite+aiosqlite:///:memory:",
    )


@pytest.fixture(autouse=True)
def isolate_logging(monkeypatch: MonkeyPatch) -> None:
    """Keep pytest capture active while exercising application factories."""
    monkeypatch.setattr(main, "configure_logging", Mock())
