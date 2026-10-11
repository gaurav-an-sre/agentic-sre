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
    (--no-allow-unauthenticated); the server itself trusts the caller identity. IAM at the edge is the boundary — the SDK's DNS-rebinding Host check only
    supports exact hosts and protects browsers, so it's off for service-to-service calls."""
    from mcp.server.transport_security import TransportSecuritySettings

    app = server.streamable_http_app(
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
