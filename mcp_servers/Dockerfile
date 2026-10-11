# One image, four services: MCP_SERVER selects which (set per Cloud Run service in 70_mcp_servers.sh).
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY agents ./agents
COPY mcp_servers ./mcp_servers
COPY evidence ./evidence
RUN pip install --no-cache-dir . "mcp>=2,<3"
ENV PORT=8080 SRE_SOURCE=gcp MCP_SERVER=observability
CMD ["sh", "-c", "python -m mcp_servers ${MCP_SERVER}"]
