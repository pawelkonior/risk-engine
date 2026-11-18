from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import cast

from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from pytest import CaptureFixture, MonkeyPatch
from sqlalchemy.exc import StatementError

from app.core.config import Settings
from app.core.logging import RequestContextFilter, configure_logging
from app.main import create_app

_ORIGIN = "https://client.example"
_SECRET = "security-regression-canary"


class JsonPayload(BaseModel):
    name: str


async def _oversized_json() -> AsyncIterator[bytes]:
    yield b'{"name":"' + b"a" * 800
    yield b"b" * 800 + b'"}'


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        request_body_max_bytes=1_024,
        cors_allowed_origins=[_ORIGIN],
    )


async def test_chunked_json_is_rejected_before_pydantic_parsing() -> None:
    application = create_app(_settings())

    async def accept(payload: JsonPayload) -> JsonPayload:
        return payload

    application.add_api_route("/payload", accept, methods=["POST"])

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        for extra_headers in ({}, {"Content-Length": "1"}):
            response = await client.post(
                "/payload",
                content=_oversized_json(),
                headers={"Content-Type": "application/json", **extra_headers},
            )
            assert response.status_code == 413
            assert response.json()["error"]["code"] == "request_too_large"


async def test_cors_and_request_id_survive_limit_and_unexpected_errors() -> None:
    application = create_app(_settings())

    async def accept(payload: JsonPayload) -> JsonPayload:
        return payload

    async def broken() -> None:
        raise RuntimeError(_SECRET)

    application.add_api_route("/payload", accept, methods=["POST"])
    application.add_api_route("/broken", broken, methods=["GET"])
    headers = {"Origin": _ORIGIN, "X-Request-ID": "security-request"}

    async with AsyncClient(
        transport=ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        too_large = await client.post("/payload", content=b"a" * 1_025, headers=headers)
        failed = await client.get("/broken", headers=headers)

    assert too_large.status_code == 413
    assert failed.status_code == 500
    for response in (too_large, failed):
        assert response.headers["X-Request-ID"] == "security-request"
        assert response.headers["Access-Control-Allow-Origin"] == _ORIGIN
        assert response.json()["error"]["request_id"] == "security-request"
        assert _SECRET not in response.text


async def test_database_errors_and_request_values_do_not_leak_to_logs(
    capsys: CaptureFixture[str], monkeypatch: MonkeyPatch
) -> None:
    application = create_app(_settings())
    # Factories normally preserve pytest logging capture. Exercise the real
    # stdout formatter here while restoring pytest handlers after this test.
    root_logger = logging.getLogger()
    monkeypatch.setattr(root_logger, "handlers", list(root_logger.handlers))
    monkeypatch.setattr(root_logger, "level", root_logger.level)
    configure_logging()
    # The HTTPX test client's own INFO log includes the complete requested URL.
    monkeypatch.setattr(logging.getLogger("httpx"), "level", logging.WARNING)

    async def broken() -> None:
        raise StatementError(
            "database driver failed",
            "INSERT INTO accounts (token) VALUES (:token)",
            {"token": _SECRET},
            RuntimeError(f"postgresql://alice:{_SECRET}@db.example/application"),
        )

    async def reset(token: str) -> dict[str, bool]:
        return {"ok": bool(token)}

    application.add_api_route("/broken", broken, methods=["GET"])
    application.add_api_route("/reset/{token}", reset, methods=["GET"])

    async with AsyncClient(
        transport=ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get("/broken")
        await client.get(
            f"/reset/{_SECRET}?access_token={_SECRET}",
            headers={"Authorization": f"Bearer {_SECRET}", "Cookie": f"session={_SECRET}"},
        )
        await client.get(f"/unknown/{_SECRET}?token={_SECRET}")

    output = capsys.readouterr().out
    assert response.status_code == 500
    assert _SECRET not in response.text
    assert _SECRET not in output
    assert "Unhandled application error" in output
    assert "/reset/{token}" in output
    assert "unmatched" in output


def test_log_filter_removes_exception_messages_source_and_locals() -> None:
    try:
        raise StatementError(
            _SECRET,
            "INSERT INTO accounts VALUES (:secret)",
            {"secret": _SECRET},
            RuntimeError(f"postgresql://alice:{_SECRET}@db.example/application"),
        )
    except StatementError as error:
        record = logging.LogRecord(
            "uvicorn.error",
            logging.ERROR,
            __file__,
            1,
            "Exception in ASGI application",
            (),
            (type(error), error, error.__traceback__),
        )
        record.exc_text = f"Cached traceback contains {_SECRET}"

    assert RequestContextFilter().filter(record) is True
    assert record.exc_info is None
    assert record.exc_text is None
    metadata = cast("dict[str, object]", record.__dict__)
    assert str(metadata["exception_type"]).endswith("StatementError")
    frames = cast("list[dict[str, object]]", metadata["exception_frames"])
    assert frames
    assert _SECRET not in json.dumps(frames)
    for frame in frames:
        assert "locals" not in frame
        assert "source" not in frame
        assert "line" not in frame or isinstance(frame["line"], int)
