#!/usr/bin/env bash
# One command from clone to ready. Re-runnable.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  cp .env.example .env
  sed -i.bak "s/^N8N_OWNER_PASSWORD=.*/N8N_OWNER_PASSWORD=Coffee-$(openssl rand -hex 6)-Demo1/" .env && rm -f .env.bak
fi

command -v ollama >/dev/null || { echo "Install Ollama first: https://ollama.com"; exit 1; }
ollama pull nomic-embed-text
ollama pull "${CHAT_MODEL:-qwen3:8b}"

uv sync --managed-python -q
docker compose up -d --build
./setup/init_cluster.sh
uv run python setup/init_n8n.py
uv run coffee reset
echo
echo "✓ Ready.  Quality console: http://localhost:8000   (the app container)"
echo "         Terminal:        docker compose exec app coffee walkthrough"
echo "  Couchbase UI http://localhost:8091 · MCP http://localhost:8001/mcp · n8n http://localhost:5678 · inbox http://localhost:8025"
