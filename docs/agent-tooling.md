# Official skills and MCP for Codex

The template vendors selected first-party skills in `.agents/skills` and keeps
project MCP configuration in `.codex/config.toml`. Agent guidance is in English.
The existing nine Spec Kit skills remain the feature planning workflow.

## Included skills

| Skill                          | Publisher | Use                                                                     |
| ------------------------------ | --------- | ----------------------------------------------------------------------- |
| `langchain-build-agent`        | LangChain | Extend the existing LangGraph state machine and agent workflows.        |
| `langfuse`                     | Langfuse  | Inspect traces; develop prompts, datasets, evaluators, and experiments. |
| `qdrant-advisor`               | Qdrant    | Retrieval, filters, indexes, embedding profiles, and operations.        |
| `postgres-best-practices`      | Neon      | General PostgreSQL schema, queries, transactions, and pooling.          |
| `fastapi`                      | FastAPI   | API contracts, Pydantic, dependencies, responses, and streaming.        |
| `playwright-cli`               | Microsoft | Explore the running UI and debug Playwright tests.                      |
| `vercel-react-best-practices`  | Vercel    | React rendering, requests, effects, and bundle performance.             |
| `pull-request-authoring`       | GitHub    | Prepare and manage pull requests.                                       |
| `pull-request-review-feedback` | GitHub    | Address review comments on the current pull request.                    |
| `triage-issue`                 | Atlassian | Investigate bugs, find duplicates, and prepare Jira issues.             |
| `search-company-knowledge`     | Atlassian | Gather Jira and Confluence context before planning work.                |

[The skill lock file](../.agents/skills.lock.json) records the upstream repository,
full commit SHA, original path, and license for each new skill. All upstream skill
files are preserved unchanged, including references. The FastAPI skill matches
the installed FastAPI 0.163.1. Spec Kit has its own release and integration state.

## Install the local tools

After the normal `make install`, from the checkout root using the Node version
in `.nvmrc`:

```bash
make agent-install
make agent-check
```

This installs `@langfuse/cli` 1.3.1 from the separate
`.agents/tools/package-lock.json`. The Playwright wrapper uses the official
`playwright cli` entrypoint from the existing stable web dependency, 1.65.1.
Microsoft documents this local installation mode. It avoids adding the standalone
`@playwright/cli` package, whose releases pin alpha Playwright snapshots.
Neo4j MCP 2.1.1 runs in an isolated uv script
environment locked in `.codex/neo4j_mcp.py.lock`. Additional agent tooling stays
outside the API and web runtime dependencies and deployment builds.

Use the pinned wrappers instead of downloading an unpinned CLI through `npx`:

```bash
.agents/bin/playwright-cli open http://127.0.0.1:8080
.agents/bin/playwright-cli snapshot
.agents/bin/playwright-cli close
.agents/bin/langfuse api __schema
```

Alternatively, prepend the wrappers for a terminal session:

```bash
export PATH="$PWD/.agents/bin:$PATH"
```

`playwright-cli` complements the existing regression suite; continue running
`make e2e` and the local pre-commit checks. Its browser output is ignored by Git.

Codex discovers the project skills automatically. New skills are available on
the next turn; reload Codex if its skill picker has not refreshed. Project MCP
configuration is loaded for a trusted checkout on a new Codex session. Check
the effective servers with `codex mcp list` or `/mcp` in Codex CLI.

## MCP servers

| Server                | Official endpoint / implementation    | Access                                         |
| --------------------- | ------------------------------------- | ---------------------------------------------- |
| `langchain-docs`      | `https://docs.langchain.com/mcp`      | Documentation search and guides.               |
| `langchain-reference` | `https://reference.langchain.com/mcp` | API search and symbol reference.               |
| `langfuse-docs`       | `https://langfuse.com/api/mcp`        | Documentation search and pages.                |
| `qdrant-docs`         | `https://search.qdrant.tech/mcp`      | Documentation search and pages.                |
| `github`              | `https://api.githubcopilot.com/mcp/`  | Repository context and pull requests.          |
| `atlassian`           | `https://mcp.atlassian.com/v2/mcp`    | Jira and Confluence through Rovo v2.           |
| `neo4j`               | `neo4j-mcp-server==2.1.1`             | Read-only schema inspection and native Cypher. |

The four documentation servers need no credentials. Explicit tool allowlists
exclude their feedback submission tools. They receive the documentation queries
you send to them. The GitHub toolsets cover context, repositories, and pull
requests; Actions and dependency/security tooling are outside this configuration.
The vendored GitHub skills work with the normal MCP tools, so the experimental
MCP skills extension is unnecessary.

### GitHub authentication

The local HTTP header helper uses, in order, `GITHUB_PERSONAL_ACCESS_TOKEN`,
`GH_TOKEN`, `GITHUB_TOKEN`, or the existing `gh auth token --hostname github.com`
login. Install and authenticate the official GitHub CLI if no token is available:

```bash
gh auth login --hostname github.com
```

The helper passes credentials directly to Codex without storing them in project
files. Never display its output or put tokens into TOML, chat, or logs.
Codex's explicitly configured bearer token or stored OAuth credentials take
precedence over a helper-provided Authorization header.

### Atlassian authentication

Complete the account-specific OAuth login once:

```bash
make agent-login-atlassian
```

Follow the browser sign-in flow and select the intended Atlassian Cloud site.
Codex stores OAuth credentials outside the repository. The installed Atlassian
skills target v2, including its `discover`/`execute` tool discovery workflow.
Use the project's `atlassian` server for them: legacy connector tools have
different names and parameter contracts.

### Neo4j and the two graphs

Start the existing local database before using its MCP:

```bash
docker compose up -d --wait neo4j
```

The wrapper reads the root `.env` as data. Shell variables take precedence.
The Compose defaults work without a local `.env`; `NEO4J_BOLT_PORT` and
`NEO4J_PASSWORD` follow the existing Compose settings. Set `NEO4J_MCP_URI`,
`NEO4J_MCP_USERNAME`, `NEO4J_MCP_PASSWORD`, and `NEO4J_MCP_DATABASE` for an explicit
external database. External connections require an explicit MCP password.
Local development credentials are never used as the fallback for an external URI.

The server exposes only `get-schema` and `read-cypher`, enforces read-only query classification,
and disables MCP telemetry. The template also disables Bolt telemetry on the
local Neo4j server. The upstream MCP does not expose a separate driver telemetry
switch; external Neo4j services control the corresponding server setting.

The official MCP requires APOC even during its initial handshake. Compose enables
the APOC Core jar bundled with the pinned Neo4j image and allows only its
`apoc.meta.schema` procedure. External databases must provide this procedure too.
The application adapters continue to use native Cypher. Schema inspection also
works through:

```cypher
CALL db.schema.visualization();
SHOW CONSTRAINTS;
SHOW INDEXES;
```

Preserve the existing knowledge/source graph model and namespace filters
described in [the AI guide](ai.md). MCP is a development tool and does not replace
the application's adapters or SQL indexing ledger.

### Langfuse data access

`langfuse-docs` reads documentation. Use `.agents/bin/langfuse` for the actual
Langfuse project's API. The wrapper maps root `.env` and shell settings to the
official CLI's `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_SECRET_KEY`.
It accepts the corresponding `APP_LANGFUSE_*` settings as well. Explicit standard
CLI settings take precedence. The local Compose port and development keys are
the fallback only for a loopback URL.

For a remote Langfuse instance, provide its URL and project keys through the
environment or ignored root `.env`. Use the API schema served by that instance
when working with version-specific functionality.

## Apply vendor guidance within this template

Read the existing configuration and linked platform documentation before applying
a skill's defaults:

- LangChain: extend the native `StateGraph` and existing HTTP adapters. A skill's
  preference for Deep Agents on new autonomous agents is not a migration task.
- Langfuse: retain the explicit OTLP integration and default-off content capture.
  LangSmith, unrelated telemetry, and GitHub Actions remain disabled.
- FastAPI: retain SQLAlchemy, Pyright, asyncio, and Vercel. Do not switch to
  SQLModel, `ty`, Asyncer, FastAPI Cloud, or automatic OpenTelemetry because they
  appear in upstream recommendations.
- Vercel React: apply the React/Vite rules. Next.js, RSC, Server Actions, and
  Next-specific imports do not apply to this SPA. Do not add analytics.
- PostgreSQL: validate changes against the actual SQLAlchemy models and migrations.
  PostgreSQL-only extensions and SQL must not break the SQLite development mode.
- GitHub/Jira: carry out remote writes only within the user's authorized task.
  Skills do not independently authorize publishing comments, tickets, or merges.

The smaller set avoids duplicate PostgreSQL guides, LangSmith integrations,
migration-only Langfuse skills, and the heavier LangChain benchmark framework.
Qdrant's data MCP is omitted because its default embedding/collection workflow
does not implement this template's embedding profiles and namespace boundaries.
Community Neo4j skills are outside the first-party selection.

## Updating

Update a skill intentionally: resolve a reviewed upstream revision to a full SHA,
use Codex's official `skill-installer` with `.agents/skills` as the destination,
review references and licenses, and update the skill lock file. Preserve upstream
files; keep project-specific decisions in this guide and `AGENTS.md`.
Qdrant Advisor fetches current hosted guidance, so its remote content changes
independently of the pinned router. Hosted MCP endpoints are provider-managed;
their server implementation cannot be pinned locally.

Update CLI versions in `.agents/tools/package.json` and regenerate its npm lock.
For Neo4j MCP, update the script metadata and run:

```bash
uv lock --script .codex/neo4j_mcp.py
make agent-install
make agent-check
```

After changes, verify MCP tool catalogs and the relevant read operations, then
run the existing local quality checks.

Sources: [LangChain skills](https://github.com/langchain-ai/langchain-skills),
[Langfuse skills](https://github.com/langfuse/skills),
[Qdrant skills](https://qdrant.tech/documentation/agentic-tools/skills/),
[Neon PostgreSQL skills](https://github.com/neondatabase/postgres-skills),
[FastAPI skills](https://fastapi.tiangolo.com/ai-development/),
[Playwright skills](https://playwright.dev/agent-cli/skills),
[Vercel skills](https://github.com/vercel-labs/agent-skills),
[GitHub Codex integration](https://github.com/github/github-mcp-server/blob/v2.2.0/docs/installation-guides/install-codex.md),
[Atlassian skills compatibility](https://github.com/atlassian/atlassian-mcp-server/blob/main/skills/README.md),
[Neo4j MCP](https://neo4j.com/docs/mcp/current/),
[Codex MCP configuration](https://developers.openai.com/codex/mcp).
