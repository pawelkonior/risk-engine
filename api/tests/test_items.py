import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.core.config import Settings
from app.main import create_app
from app.modules.items.schemas import ItemUpdate
from app.platform.database import DatabaseRuntime


def postgres_test_url(value: str) -> str:
    message = "TEST_DATABASE_URL must use PostgreSQL with a database name starting with test_"
    try:
        parsed = make_url(value)
    except ArgumentError:
        raise ValueError(message) from None
    if parsed.get_backend_name() != "postgresql" or not (parsed.database or "").startswith("test_"):
        raise ValueError(message)
    return value


@pytest.mark.parametrize(
    "value",
    [
        "postgresql+psycopg://user:secret@localhost/app",
        "postgresql://user:secret@localhost/postgres",
        "postgresql://user:secret@localhost/template1",
        "sqlite:///test_app",
        "not-a-database-url",
    ],
)
def test_migration_checks_reject_non_test_databases(value: str) -> None:
    with pytest.raises(ValueError, match="database name starting with test_") as error:
        postgres_test_url(value)
    assert "secret" not in str(error.value)


@pytest.fixture(params=["sqlite", "postgresql"])
def migrated_url(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[str]:
    """Run the same migration lifecycle against SQLite and an opt-in test PostgreSQL."""
    backend = str(request.param)
    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    if backend == "postgresql":
        value = os.environ.get("TEST_DATABASE_URL")
        if not value:
            pytest.skip("set TEST_DATABASE_URL to a dedicated PostgreSQL test database")
        url = postgres_test_url(value)
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("APP_")
        and key not in {"DATABASE_URL", "DIRECT_DATABASE_URL", "VERCEL"}
    }
    environment.update(APP_DATABASE_URL=url, APP_DATABASE_MIGRATION_URL=url)

    def migrate(*arguments: str) -> None:
        completed = subprocess.run(  # noqa: S603 - fixed interpreter and Alembic command
            [sys.executable, "-m", "alembic", *arguments],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            pytest.fail(
                f"Alembic {' '.join(arguments)} failed with exit status {completed.returncode}",
                pytrace=False,
            )

    migrate("upgrade", "head")
    migrate("check")
    migrate("downgrade", "base")
    migrate("upgrade", "head")
    try:
        yield url
    finally:
        migrate("downgrade", "base")


@pytest.fixture
async def client(migrated_url: str) -> AsyncIterator[AsyncClient]:
    application = create_app(
        Settings(_env_file=None, environment="test", database_url=migrated_url)
    )
    runtime: DatabaseRuntime = application.state.database
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        yield client
    await runtime.close()


async def test_item_crud_and_pagination(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/items")).json()["items"] == []
    created = await client.post(
        "/api/v1/items", json={"title": "  First item  ", "description": "Body"}
    )
    assert created.status_code == 201
    item = created.json()
    item_id = item["id"]
    assert item["title"] == "First item"
    assert item["created_at"].endswith("Z")
    fetched = await client.get(f"/api/v1/items/{item_id}")
    assert fetched.status_code == 200
    assert fetched.json() == item
    await client.post("/api/v1/items", json={"title": "Second item"})
    first_page = (await client.get("/api/v1/items?limit=1")).json()
    assert len(first_page["items"]) == 1
    assert first_page["has_more"]
    second_page = (await client.get("/api/v1/items?limit=1&offset=1")).json()
    assert len(second_page["items"]) == 1
    assert not second_page["has_more"]
    assert first_page["items"][0]["id"] != second_page["items"][0]["id"]
    updated = await client.patch(f"/api/v1/items/{item_id}", json={"title": "Updated"})
    assert updated.status_code == 200
    assert updated.json()["description"] == "Body"
    assert updated.json()["title"] == "Updated"
    assert updated.json()["created_at"] == item["created_at"]
    cleared = await client.patch(f"/api/v1/items/{item_id}", json={"description": None})
    assert cleared.json()["description"] is None
    deleted = await client.delete(f"/api/v1/items/{item_id}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert (await client.get(f"/api/v1/items/{item_id}")).status_code == 404
    assert (
        await client.patch(f"/api/v1/items/{item_id}", json={"title": "Lost"})
    ).status_code == 404
    assert (await client.delete(f"/api/v1/items/{item_id}")).status_code == 404


async def test_invalid_resource_requests(client: AsyncClient) -> None:
    for payload in [{"title": " "}, {"title": "x" * 201}, {"title": "OK", "unknown": 1}, {}]:
        assert (await client.post("/api/v1/items", json=payload)).status_code == 422
    for query in ["limit=0", "limit=101", "offset=-1", "limit=abc"]:
        assert (await client.get(f"/api/v1/items?{query}")).status_code == 422
    assert (await client.get("/api/v1/items/invalid-uuid")).status_code == 422
    assert (await client.get(f"/api/v1/items/{uuid4()}")).status_code == 404
    for payload in [{}, {"title": None}, {"description": "x" * 10_001}]:
        response = await client.patch(f"/api/v1/items/{uuid4()}", json=payload)
        assert response.status_code == 422


def test_update_requires_a_change_and_non_null_title() -> None:
    with pytest.raises(ValidationError):
        ItemUpdate()
    with pytest.raises(ValidationError):
        ItemUpdate(title=None)
    assert ItemUpdate(description=None).model_fields_set == {"description"}
