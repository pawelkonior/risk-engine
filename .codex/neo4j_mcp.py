# /// script
# requires-python = ">=3.14,<3.15"
# dependencies = ["neo4j-mcp-server==2.1.1", "python-dotenv==1.2.4"]
# ///
"""Run the official Neo4j MCP against local Compose or an explicit remote URI."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values
from neo4j_mcp_server import main


def configure() -> None:
    values = dotenv_values(Path(__file__).resolve().parents[1] / ".env")

    def setting(*names: str, default: str = "") -> str:
        for source in (os.environ, values):
            for name in names:
                if value := source.get(name):
                    return value
        return default

    port = setting("NEO4J_BOLT_PORT", default="7687")
    uri = setting("NEO4J_MCP_URI", default=f"bolt://127.0.0.1:{port}")
    local = urlsplit(uri).hostname in {"localhost", "127.0.0.1", "::1"}
    password = (
        setting("NEO4J_MCP_PASSWORD", "NEO4J_PASSWORD", default="neo4j-local-only")
        if local
        else setting("NEO4J_MCP_PASSWORD")
    )
    if not password:
        raise SystemExit("Set NEO4J_MCP_PASSWORD for the external Neo4j database.")

    os.environ.update(
        NEO4J_MCP_URI=uri,
        NEO4J_MCP_USERNAME=setting("NEO4J_MCP_USERNAME", default="neo4j"),
        NEO4J_MCP_PASSWORD=password,
        NEO4J_MCP_DATABASE=setting("NEO4J_MCP_DATABASE", default="neo4j"),
        NEO4J_MCP_TRANSPORT_MODE="stdio",
        NEO4J_MCP_READ_ONLY="true",
        NEO4J_MCP_TOOLS="get-schema,read-cypher",
        NEO4J_MCP_TELEMETRY="false",
        NEO4J_MCP_REQUEST_TIMEOUT="45s",
    )


if __name__ == "__main__":
    configure()
    main()
