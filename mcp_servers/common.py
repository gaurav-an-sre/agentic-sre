from __future__ import annotations

import os

import uvicorn
from mcp.server.mcpserver import MCPServer

SOURCE = os.environ.get("SRE_SOURCE", "bundle")
PROJECT = os.environ.get("PROJECT", "")
REGION = os.environ.get("REGION", "asia-southeast1")


def gcp_mode() -> bool:
    return SOURCE == "gcp"


def serve(server: MCPServer) -> None:
    """Streamable-HTTP on $PORT (Cloud Run contract). Auth is IAM at the Cloud Run edge
    (--no-allow-unauthenticated, ingress internal); the server itself trusts the caller identity."""
    uvicorn.run(server.streamable_http_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
