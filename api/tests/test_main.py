from typing import cast
from unittest.mock import Mock, create_autospec

from pytest import MonkeyPatch

from app import main
from app.core.config import Settings
from app.platform.database import DatabaseRuntime


def test_application_factory_configures_identity_and_documentation() -> None:
    hidden = main.create_app(Settings(_env_file=None, name="Orders API", docs_enabled=False))
    exposed = main.create_app(Settings(_env_file=None, docs_enabled=True))
    assert hidden.title == "Orders API"
    assert hidden.docs_url is None
    assert hidden.redoc_url is None
    assert hidden.openapi_url is None
    assert exposed.docs_url == "/docs"
    assert exposed.redoc_url == "/redoc"
    assert isinstance(hidden.state.database, DatabaseRuntime)


def test_factory_configures_logging_without_lifespan(monkeypatch: MonkeyPatch) -> None:
    configure = Mock()
    monkeypatch.setattr(main, "configure_logging", configure)
    main.create_app(Settings(_env_file=None))
    configure.assert_called_once_with("INFO")


async def test_lifespan_closes_database_without_startup_network_io(test_settings: Settings) -> None:
    application = main.create_app(test_settings)
    database = create_autospec(DatabaseRuntime, instance=True)
    application.state.database = database
    async with main.lifespan(application):
        database.ping.assert_not_awaited()
        database.close.assert_not_awaited()
    database.close.assert_awaited_once_with()


def test_factory_disables_native_telemetry_even_with_host_auto_setup(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("FASTAPI_OTEL_AUTO_CONFIGURE", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
    application = main.create_app(Settings(_env_file=None))

    # Verify the framework's resolved configuration, including environment precedence.
    telemetry = cast("dict[str, object]", vars(application)["_telemetry"])
    for signal in ("tracing", "metrics", "logs", "operation_spans", "auto_configure"):
        assert telemetry[signal] is False
    assert vars(application)["_native_telemetry"].enabled() is False
