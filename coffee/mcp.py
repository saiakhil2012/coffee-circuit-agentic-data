"""Connect to the open-source Couchbase MCP server, running in read-only mode."""

import json
import shlex
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

from . import config

# Every server tool except the two the agent may use is switched off on the server (one name per line).
DISABLED_TOOLS = config.ROOT / "setup" / "mcp-disabled-tools.txt"


def client() -> MultiServerMCPClient:
    """The MCP server runs as its own service (streamable HTTP); MCP_URL=stdio starts it as a child process instead."""
    if config.MCP_URL != "stdio":
        return MultiServerMCPClient({"couchbase": {"transport": "streamable_http", "url": config.MCP_URL}})
    config.LOGS.mkdir(exist_ok=True)
    server = shlex.quote(str(config.ROOT / ".venv" / "bin" / "couchbase-mcp-server"))
    log = shlex.quote(str(config.LOGS / "mcp-server.log"))
    return MultiServerMCPClient(
        {
            "couchbase": {
                "transport": "stdio",
                "command": "/bin/sh",
                # stderr goes to a log file so the stage terminal only shows the agent's trace
                "args": ["-c", f"exec {server} 2>>{log}"],
                "env": {
                    "PATH": "/usr/bin:/bin",
                    "CB_CONNECTION_STRING": config.CB_CONNECTION_STRING,
                    "CB_USERNAME": config.CB_USERNAME,
                    "CB_PASSWORD": config.CB_PASSWORD,
                    "CB_MCP_READ_ONLY_MODE": "true",
                    "CB_MCP_DISABLED_TOOLS": str(DISABLED_TOOLS),
                    "CB_MCP_LOG_LEVEL": "error",
                },
            }
        }
    )


def parse(result: Any) -> Any:
    """MCP tool results arrive as content blocks; return the decoded JSON rows (or the error text)."""
    if isinstance(result, list):
        texts = [b.get("text", "") for b in result if isinstance(b, dict)]
        result = "".join(texts)
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return result
    return result


class Sql:
    """Runs SQL++ through the MCP server's run_sql_plus_plus_query tool."""

    def __init__(self, tool):
        self.tool = tool

    async def __call__(self, statement: str, **params) -> Any:
        out = await self.tool.ainvoke(
            {
                "bucket_name": config.BUCKET,
                "scope_name": config.SCOPE,
                "query": statement,
                "named_parameters": params or None,
            }
        )
        return parse(out)
