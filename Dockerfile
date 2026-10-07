# One image, two services (see docker-compose.yml): the Quality console (FastAPI + LangGraph agent) and the
# open-source Couchbase MCP server, which is a dependency of the project and runs as its own container over HTTP.
FROM python:3.12-slim

RUN pip install --no-cache-dir uv==0.12.17
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# dependencies first, so code changes don't reinstall them
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY coffee ./coffee
COPY queries ./queries
COPY data/generate.py ./data/generate.py
COPY ingest ./ingest
COPY setup/mcp-disabled-tools.txt ./setup/
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["coffee", "web", "--host", "0.0.0.0", "--port", "8000"]
