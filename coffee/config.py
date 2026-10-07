import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUERIES = ROOT / "queries"
LOGS = ROOT / "logs"

CB_CONNECTION_STRING = os.getenv("CB_CONNECTION_STRING", "couchbase://localhost")
CB_USERNAME = os.getenv("CB_USERNAME", "Administrator")
CB_PASSWORD = os.getenv("CB_PASSWORD", "password")
BUCKET, SCOPE = "store", "ops"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
CHAT_MODEL = os.getenv("CHAT_MODEL", "qwen3:8b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

N8N_NOTIFY_URL = os.getenv("N8N_NOTIFY_URL", "http://localhost:5678/webhook/recall-notify")
MAILPIT_URL = os.getenv("MAILPIT_URL", "http://localhost:8025")

# The Couchbase MCP server (its own container). "stdio" starts it as a child process of this app instead.
MCP_URL = os.getenv("MCP_URL", "http://localhost:8001/mcp")
# The only MCP tools the agent is shown. Everything else is disabled server-side (setup/mcp-disabled-tools.txt).
MCP_ALLOWED_TOOLS = ["run_sql_plus_plus_query", "get_document_by_id"]


def sql(name: str) -> str:
    """Load a SQL++ recipe from queries/ (strip the leading comment so the trace stays readable)."""
    text = (QUERIES / name).read_text()
    if text.startswith("/*"):
        text = text[text.index("*/") + 2 :]
    return text.strip()
