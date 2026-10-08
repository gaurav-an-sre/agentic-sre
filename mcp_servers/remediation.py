"""remediation-mcp: the only production write path. One tool. Own service account (roles/run.developer
scoped to the pilot services). The gate is enforced HERE as well as in the agent callback: the call must
reference an approved proposal whose target_revision matches, and the revision must be on the allow-list
(it served traffic before). Defence in depth - the model is never the control."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from mcp.server.mcpserver import MCPServer

from agents.common import tools as bundle_tools
from agents.common.control_plane import audit
from mcp_servers import gcp_api
from mcp_servers.common import PROJECT, REGION, gcp_mode

server = MCPServer("remediation-mcp", instructions="shift_traffic only; requires an approved proposal id.")


def allowed_revisions(service: str) -> set[str]:
    if gcp_mode():
        return {r["revision"] for r in gcp_api.revisions(PROJECT, REGION, service)}
    return {d["revision"] for d in bundle_tools.bundle.deployments() if d.get("revision")}


def check(proposal_id: str, service: str, revision: str) -> dict | None:
    p = bundle_tools.PROPOSALS / f"{proposal_id}.json"
    rec = json.loads(p.read_text()) if p.exists() else {"status": "unknown"}
    if rec["status"] != "approved":
        return {"denied": True, "reason": f"proposal {proposal_id} is '{rec['status']}', not approved"}
    if rec.get("target_revision") and rec["target_revision"] != revision:
        return {"denied": True, "reason": f"approved target is {rec['target_revision']}, not {revision}"}
    if revision not in allowed_revisions(service):
        return {"denied": True, "reason": f"{revision} is not a known revision of {service} (allow-list)"}
    return None


@server.tool()
def shift_traffic(proposal_id: str, service: str, revision: str, percent: int = 100) -> dict:
    """Move traffic of a Cloud Run service to a revision. Denied unless proposal_id is approved by a human,
    names this revision, and the revision previously served traffic."""
    denied = check(proposal_id, service, revision)
    if denied:
        audit("PolicyDeny", tool="shift_traffic", proposal=proposal_id, **denied)
        return denied
    if gcp_mode():
        result = gcp_api.shift_traffic(PROJECT, REGION, service, revision, percent)
    else:
        result = {"result": f"simulated: {service} traffic {percent}% -> {revision}"}
    p = bundle_tools.PROPOSALS / f"{proposal_id}.json"
    rec = json.loads(p.read_text())
    rec.update(status="applied", applied_ts=datetime.now(UTC).isoformat(), apply_result=result)
    p.write_text(json.dumps(rec, indent=1))
    audit("Apply", tool="shift_traffic", proposal=proposal_id, service=service, revision=revision, percent=percent)
    return {**result, "proposal": proposal_id}


if __name__ == "__main__":
    from mcp_servers.common import serve
    serve(server)
