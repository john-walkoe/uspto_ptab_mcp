FROM python:3.11-slim

# curl for the healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Dependency layer — cached unless pyproject.toml / uv.lock change.
# --no-install-project: deps only (hatchling needs src/ to build the project itself)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Source + runtime config (field_configs.yaml + reference/ are read at startup)
COPY src/ ./src/
COPY field_configs.yaml ./
COPY reference/ ./reference/
COPY scripts/ ./scripts/

RUN uv sync --frozen --no-dev

# HTTP transport. Port is overridden per-service in the deployment compose (8004);
# the document proxy binds PTAB_PROXY_PORT (default 8083) in the same process.
ENV FASTMCP_TRANSPORT=http
ENV FASTMCP_HOST=0.0.0.0
ENV FASTMCP_PORT=8004

EXPOSE 8004 8083

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=20s \
  CMD curl -sf "http://localhost:${FASTMCP_PORT:-8004}/health" || exit 1

CMD ["uv", "run", "ptab-mcp"]
