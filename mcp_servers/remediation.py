"""remediation-mcp: the only production write path. One tool. Own service account (roles/run.developer
scoped to the pilot services). The gate is enforced HERE as well as in the agent callback: the call must
reference an approved proposal whose target_revision matches, the revision must be on the allow-list
(it served traffic before), and the pre-flight checks in mcp_servers.safety must pass. Defence in depth -
the model is never the control."""

from __future__ import annotations

from datetime import UTC, datetime

from mcp.server.mcpserver import MCPServer

from agents.common import proposals
from agents.common import tools as bundle_tools
from agents.common.control_plane import audit
from mcp_servers import gcp_api, safety
from mcp_servers.common import PROJECT, REGION, gcp_mode

server = MCPServer("remediation-mcp", instructions="shift_traffic only; requires an approved proposal id and the "
                                                   "open incident id. Call with dry_run=true first.")


def current_split(service: str) -> dict[str, int]:
    if gcp_mode():
        return {r["revision"]: r["traffic_percent"] for r in gcp_api.revisions(PROJECT, REGION, service) if r["traffic_percent"]}
    return {d["revision"]: 100 for d in bundle_tools.bundle.deployments()[-1:] if d.get("revision")}


def allowed_revisions(service: str) -> set[str]:
    if gcp_mode():
        return {r["revision"] for r in gcp_api.revisions(PROJECT, REGION, service)}
    return {d["revision"] for d in bundle_tools.bundle.deployments() if d.get("revision")}


def check(proposal_id: str, service: str, revision: str) -> dict | None:
    rec = proposals.load(proposal_id) or {"status": "unknown"}
    if rec["status"] != "approved":
        return {"denied": True, "reason": f"proposal {proposal_id} is '{rec['status']}', not approved"}
    if rec.get("target_revision") and rec["target_revision"] != revision:
        return {"denied": True, "reason": f"approved target is {rec['target_revision']}, not {revision}"}
    if revision not in allowed_revisions(service):
        return {"denied": True, "reason": f"{revision} is not a known revision of {service} (allow-list)"}
    return None


@server.tool()
def shift_traffic(proposal_id: str, service: str, revision: str, percent: int = 100,
                  incident_id: str = "", dry_run: bool = False, override_hold: str = "") -> dict:
    """Move traffic of a Cloud Run service to a revision. Denied unless proposal_id is approved by a human,
    names this revision, the revision previously served traffic, incident_id is the open incident and the
    red button is not pressed. Risk holds (another change in flight, change freeze) stop the call unless a
    human passes override_hold with their name. dry_run=true returns the plan and every check without
    changing anything."""
    denied = check(proposal_id, service, revision)
    if denied:
        audit("PolicyDeny", tool="shift_traffic", proposal=proposal_id, dry_run=dry_run, **denied)
        return denied
    flight = safety.pre_flight(proposal_id, incident_id)
    plan = {"service": service, "from": current_split(service), "to": {revision: percent},
            "proposal": proposal_id, "incident": incident_id, "checks": flight}
    if flight["deny"]:
        audit("PolicyDeny", tool="shift_traffic", proposal=proposal_id, dry_run=dry_run, reason=flight["deny"])
        return {"denied": True, "reason": flight["deny"], "plan": plan}
    if flight["holds"] and not override_hold:
        audit("RiskHold", tool="shift_traffic", proposal=proposal_id, dry_run=dry_run, holds=flight["holds"])
        return {"held": True, "reason": "; ".join(flight["holds"]),
                "next": "a human may re-run with override_hold=<name> after reviewing the plan", "plan": plan}
    if dry_run:
        audit("DryRun", tool="shift_traffic", proposal=proposal_id, plan=plan)
        return {"dry_run": True, "would_apply": True, "plan": plan}
    if gcp_mode():
        result = gcp_api.shift_traffic(PROJECT, REGION, service, revision, percent)
    else:
        result = {"result": f"simulated: {service} traffic {percent}% -> {revision}"}
    rec = proposals.load(proposal_id)
    rec.update(status="applied", applied_ts=datetime.now(UTC).isoformat(), apply_result=result,
               incident_id=incident_id, override_hold=override_hold or None)
    proposals.save(rec)
    audit("Apply", tool="shift_traffic", proposal=proposal_id, service=service, revision=revision, percent=percent,
          incident=incident_id, override_hold=override_hold or None)
    return {**result, "proposal": proposal_id, "plan": plan}


if __name__ == "__main__":
    from mcp_servers.common import serve
    serve(server)
