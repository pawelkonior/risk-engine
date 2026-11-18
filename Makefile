.PHONY: install up down logs check compose-check api-check web-check e2e e2e-compose hooks format ai-init ai-smoke langfuse-smoke spec-install spec-check agent-install agent-check agent-login-atlassian

.DEFAULT_GOAL := install

SPEC_KIT_VERSION := 1.4.1

spec-install:
	uv tool install --force specify-cli --from git+https://github.com/github/spec-kit.git@v$(SPEC_KIT_VERSION)

spec-check:
	@test "$$(specify --version)" = "specify $(SPEC_KIT_VERSION)" || { echo "Run make spec-install for Spec Kit $(SPEC_KIT_VERSION)"; exit 1; }
	specify integration status
	@for script in .specify/scripts/bash/*.sh; do bash -n "$$script" || exit; done
	@.specify/scripts/bash/resolve-template.sh constitution-template --json >/dev/null
	@.specify/scripts/bash/create-new-feature.sh --dry-run --json --short-name setup-check "Verify Spec Kit setup" >/dev/null

agent-install:
	@test -x web/node_modules/.bin/playwright || { echo "Run make install before make agent-install."; exit 1; }
	npm --prefix .agents/tools ci
	uv sync --script .codex/neo4j_mcp.py --locked

agent-check:
	node --test .agents/run-langfuse.test.mjs
	.agents/bin/playwright-cli --version
	.agents/bin/langfuse --version
	uv run --no-project --locked --script .codex/neo4j_mcp.py --version
	codex mcp list

agent-login-atlassian:
	codex mcp login atlassian

install:
	uv sync --project api --all-groups --locked
	npm --prefix web ci
	npm --prefix web exec -- playwright install chromium firefox webkit

up:
	docker compose up --build --wait --wait-timeout 1200

ai-init:
	docker compose run --rm ai-init

ai-smoke:
	uv run --project api --locked python api/scripts/ai_smoke.py

langfuse-smoke:
	uv run --project api --locked python api/scripts/langfuse_smoke.py

down:
	docker compose down

logs:
	docker compose logs --follow

check: compose-check api-check web-check

compose-check:
	docker compose config --quiet

api-check:
	$(MAKE) -C api check

web-check:
	npm --prefix web run check

e2e:
	npm --prefix web run test:e2e

e2e-compose:
	PLAYWRIGHT_BASE_URL=http://127.0.0.1:$${WEB_PORT:-8080} npm --prefix web run test:e2e:compose

hooks:
	uv run --project api --locked pre-commit install

format:
	$(MAKE) -C api format
	npm --prefix web run format
