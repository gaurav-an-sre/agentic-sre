"""ADK toolsets that talk to the MCP servers (SRE_TOOLS=mcp). Default stays in-process functions so
tests and evals run offline. URLs: OBS_MCP_URL, RELEASE_MCP_URL, INCIDENT_MCP_URL, REMEDIATION_MCP_URL
(Cloud Run URLs, IAM-authenticated: an identity token for the agent's service account is attached)."""

from __future__ import annotations

import os
import subprocess

from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams


def _id_token(audience: str) -> str:
    return subprocess.run(["gcloud", "auth", "print-identity-token", f"--audiences={audience}"],
                          check=True, capture_output=True, text=True).stdout.strip()


def toolset(env_var: str, tool_filter: list[str] | None = None) -> McpToolset:
    url = os.environ[env_var].rstrip("/") + "/mcp"
    headers = {"Authorization": f"Bearer {_id_token(url)}"} if url.startswith("https://") else {}
    return McpToolset(connection_params=StreamableHTTPConnectionParams(url=url, headers=headers),
                      tool_filter=tool_filter)


def use_mcp() -> bool:
    return os.environ.get("SRE_TOOLS", "local") == "mcp"
