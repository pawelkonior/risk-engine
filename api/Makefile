.PHONY: install dev migrate migration-check test lint format type docs check ai-init

install:
	uv sync --all-groups --locked

dev:
	uv run uvicorn app.main:app --reload

migrate:
	uv run alembic upgrade head

migration-check:
	uv run alembic check

test:
	uv run pytest

lint:
	uv run ruff check
	uv run ruff format --check

format:
	uv run ruff check --fix
	uv run ruff format

type:
	uv run pyright

docs:
	uv run --group docs sphinx-build -E -a -W --keep-going -b html docs docs/_build/html

check:
	uv sync --all-groups --locked
	uv run tox run-parallel

ai-init:
	uv run python -m app.platform.ai.setup
