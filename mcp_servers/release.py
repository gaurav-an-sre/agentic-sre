"""release-mcp (read-only). SA roles: run.viewer, clouddeploy.viewer."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from agents.common import tools as bundle_tools
from mcp_servers import gcp_api
from mcp_servers.common import PROJECT, REGION, gcp_mode, serve

server = MCPServer("release-mcp", instructions="Read-only Cloud Run revisions, env diffs, runtime config, runbooks.")


@server.tool()
def list_revisions(service: str = "payments-api") -> list[dict]:
    """Revisions in creation order with image, env and current traffic share. Ids are citeable."""
    return gcp_api.revisions(PROJECT, REGION, service) if gcp_mode() else bundle_tools.get_recent_deployments()


@server.tool()
def get_deploy_diff(service: str = "payments-api", revision: str = "") -> dict:
    """Env/config diff between a revision (default: the one serving traffic) and the one before it."""
    revs = list_revisions(service)
    if not revs:
        return {"error": "no revisions"}
    if gcp_mode():
        idx = next((i for i, r in enumerate(revs) if r["revision"] == revision), None) if revision else \
            max((i for i, r in enumerate(revs) if r["traffic_percent"] > 0), default=len(revs) - 1)
        cur, prev = revs[idx], (revs[idx - 1] if idx > 0 else None)
        env_c, env_p = cur["env"], (prev["env"] if prev else {})
        changed = {k: {"from": env_p.get(k), "to": env_c.get(k)} for k in set(env_c) | set(env_p) if env_c.get(k) != env_p.get(k)}
        return {"revision": cur["revision"], "previous": prev["revision"] if prev else None,
                "image": {"from": prev["image"] if prev else None, "to": cur["image"]}, "env_changes": changed}
    cur = next((d for d in revs if d.get("revision") == revision), revs[-1])
    return {"revision": cur.get("revision"), "id": cur["id"], "diff": cur.get("config_diff") or cur.get("diff"), "raw": cur}


@server.tool()
def read_config(name: str = "payments-api.env") -> dict:
    """Runtime config as deployed (bundle: config file; gcp: env of the serving revision)."""
    if not gcp_mode():
        return bundle_tools.read_config(name)
    service = name.replace(".env", "")
    live = [r for r in gcp_api.revisions(PROJECT, REGION, service) if r["traffic_percent"] > 0]
    return {"name": name, "revision": live[-1]["revision"], "env": live[-1]["env"]} if live else {"error": "no serving revision"}


@server.tool()
def get_runbook(name: str = "payments-api-rollback.md") -> dict:
    """Runbook text (Confluence in the customer's setup; the repo copy here)."""
    return bundle_tools.read_runbook(name)


if __name__ == "__main__":
    serve(server)
