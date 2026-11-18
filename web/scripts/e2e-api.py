"""Serve an isolated migrated SQLite API for local Playwright tests."""

import os
import signal
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import FrameType

API_ROOT = Path(__file__).resolve().parents[2] / "api"


def stop(_signal: int, _frame: FrameType | None) -> None:
    raise SystemExit(0)


def main() -> int:
    port = int(os.environ.get("E2E_API_PORT", "8001"))
    if not 1024 <= port <= 65535:
        raise ValueError("E2E_API_PORT must be between 1024 and 65535")
    if not (API_ROOT / "alembic.ini").is_file():
        raise RuntimeError("Local E2E requires the sibling api project")

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with TemporaryDirectory(prefix="application-e2e-") as temporary:
        database_url = f"sqlite+aiosqlite:///{Path(temporary) / 'test.db'}"
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("APP_")
            and key not in {"DATABASE_URL", "DIRECT_DATABASE_URL", "VERCEL", "VERCEL_ENV"}
        }
        environment.update(
            APP_ENVIRONMENT="test",
            APP_DOCS_ENABLED="false",
            APP_LOG_LEVEL="WARNING",
            APP_DATABASE_URL=database_url,
            APP_DATABASE_MIGRATION_URL=database_url,
            PYTHONPATH=str(API_ROOT / "src"),
        )
        server: subprocess.Popen[bytes] | None = None
        try:
            subprocess.run(  # noqa: S603 - fixed interpreter and migration command; no shell
                [
                    sys.executable,
                    "-m",
                    "alembic",
                    "-c",
                    str(API_ROOT / "alembic.ini"),
                    "upgrade",
                    "head",
                ],
                cwd=temporary,
                env=environment,
                check=True,
            )
            server = subprocess.Popen(  # noqa: S603 - fixed command and validated numeric port
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--no-access-log",
                ],
                cwd=temporary,
                env=environment,
            )
            return server.wait()
        finally:
            if server is not None and server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


if __name__ == "__main__":
    raise SystemExit(main())
