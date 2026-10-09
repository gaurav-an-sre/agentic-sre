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
    (--no-allow-unauthenticated); the server itself trusts the caller identity. Host/origin
    checks are widened to the *.a.run.app hostnames the platform routes by."""
    from mcp.server.transport_security import TransportSecuritySettings

    app = server.streamable_http_app(
        transport_security=TransportSecuritySettings(
            allowed_hosts=["*.a.run.app", "localhost", "127.0.0.1"],
            allowed_origins=["https://*.a.run.app"],
        )
    )
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
