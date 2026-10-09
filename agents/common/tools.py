"""Plain-function tools for ADK agents. Read tools only touch the frozen bundle.
`raw=True` variants exist so v1 can show what happens without pre-aggregation."""

from __future__ import annotations

import subprocess
import uuid
from datetime import UTC, datetime
from statistics import mean

from agents.common import proposals
from agents.common.bundle import ROOT, Bundle

PROPOSALS = ROOT / "proposals"
POSTMORTEMS = ROOT / "postmortems"
bundle = Bundle()


def verify_bundle() -> dict:
    """Verify the SHA-256 manifest of the frozen evidence bundle and return the incident header."""
    return {"incident": bundle.incident(), "integrity": bundle.verify()}


def get_service_health() -> dict:
    """Per-service summary: baseline vs now for every metric, plus firing alerts."""
    out: dict[str, dict] = {}
    for s in bundle.metrics():
        pts = s["points"]
        out.setdefault(s["service"], {})[s["metric"]] = {
            "baseline": round(mean(p["value"] for p in pts[:10]), 3),
            "now": round(mean(p["value"] for p in pts[-5:]), 3)}
    return {"services": out, "firing_alerts": [a for a in bundle.alerts() if a["status"] == "firing"]}


def query_metrics(service: str, metric: str) -> dict:
    """1-minute time series for one metric of one service."""
    for s in bundle.metrics():
        if s["service"] == service and s["metric"] == metric:
            return s
    return {"error": "no such series", "available": sorted({(s["service"], s["metric"]) for s in bundle.metrics()})}


def get_logs(service: str, level: str = "all", lines: int = 30) -> dict:
    """Last N log lines for a service (filtered by level). Each line has an id (L00042) - cite it."""
    lvl = level.upper()
    rows = [e for e in bundle.logs() if e["service"] == service and (lvl == "ALL" or e["level"] == lvl)]
    return {"count": len(rows), "lines": rows[-lines:]}


def get_logs_raw(service: str) -> dict:
    """v1 only: EVERY log line for a service, unaggregated. This is how v1 blew its context window."""
    return {"lines": [e for e in bundle.logs() if e["service"] == service]}


def get_alerts() -> list[dict]:
    """All alerts in the incident window."""
    return bundle.alerts()


def get_recent_deployments() -> list[dict]:
    """Deployments in the window, with config diffs and revision names."""
    return bundle.deployments()


def read_config(name: str) -> dict:
    """Read a runtime config file from the bundle (e.g. payments-api.env)."""
    try:
        return {"name": name, "content": bundle.config(name)}
    except (FileNotFoundError, ValueError) as exc:
        return {"error": str(exc)}


def read_runbook(name: str) -> dict:
    """Read a runbook by filename."""
    try:
        return {"name": name, "content": bundle.runbook(name)}
    except FileNotFoundError as exc:
        return {"error": str(exc)}


def validate_citations(evidence_refs: list[str]) -> list[str]:
    """Return the refs that do NOT exist in the bundle."""
    valid = bundle.evidence_ids()
    return [r for r in evidence_refs if r not in valid]


def propose_remediation(title: str, action: str, rationale: str, evidence_refs: list[str],
                        rollback_plan: str, target_revision: str = "") -> dict:
    """Record a remediation PROPOSAL for human approval. Changes nothing. evidence_refs must be ids
    from get_logs / get_recent_deployments / get_alerts; unknown ids are rejected."""
    bad = validate_citations(evidence_refs)
    if bad or not evidence_refs:
        return {"error": f"citation check failed: unknown or missing evidence refs {bad}"}
    pid = "P-" + uuid.uuid4().hex[:8]
    rec = {"id": pid, "status": "pending_approval", "created_ts": datetime.now(UTC).isoformat(),
           "title": title, "action": action, "rationale": rationale, "evidence_refs": evidence_refs,
           "rollback_plan": rollback_plan, "target_revision": target_revision}
    proposals.save(rec)
    return {"proposal_id": pid, "status": "pending_approval",
            "next": f"a human must run: python -m agents.v2.run approve {pid}"}


def apply_remediation(proposal_id: str) -> dict:
    """Execute an APPROVED proposal. In bundle mode it is simulated; in gcp mode it shifts Cloud Run
    traffic to a revision that already exists in the bundle. Nothing else is ever written."""
    rec = proposals.load(proposal_id)
    if rec is None:
        return {"error": "unknown proposal"}
    if rec["status"] != "approved":
        return {"error": f"proposal {proposal_id} is {rec['status']}, not approved"}
    src = bundle.incident().get("source", {})
    if src.get("type") == "gcp":
        result = _rollback_cloud_run(src, rec.get("target_revision", ""))
        if "error" in result:
            return result
    else:
        result = {"result": "simulated: " + rec["action"]}
    rec.update(status="applied", applied_ts=datetime.now(UTC).isoformat(), apply_result=result)
    proposals.save(rec)
    return {**result, "proposal": proposal_id}


def apply_remediation_ungated(action: str) -> dict:
    """v1 only: apply any free-text action immediately (simulated). Kept to show why v1 was retired."""
    return {"result": "APPLIED WITHOUT APPROVAL (simulated): " + action}


def _rollback_cloud_run(src: dict, revision: str) -> dict:
    known = {d["revision"] for d in bundle.deployments() if d.get("revision")}
    if revision not in known:
        return {"error": f"target_revision {revision!r} is not in the bundle {sorted(known)}"}
    cmd = ["gcloud", "run", "services", "update-traffic", src["service"], "--region", src["region"],
           "--project", src["project"], "--to-revisions", f"{revision}=100", "--format", "json"]
    run = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if run.returncode != 0:
        return {"error": "gcloud failed: " + run.stderr.strip()[-600:]}
    return {"result": f"traffic shifted: 100% -> {revision}", "command": " ".join(cmd[:-2])}


def write_postmortem(markdown: str) -> dict:
    """Write the postmortem markdown to postmortems/<incident>.md."""
    POSTMORTEMS.mkdir(exist_ok=True)
    path = POSTMORTEMS / f"{bundle.incident()['id']}.md"
    path.write_text(markdown)
    return {"written": str(path), "bytes": len(markdown)}


READ_TOOLS = [verify_bundle, get_service_health, query_metrics, get_logs, get_alerts,
              get_recent_deployments, read_config, read_runbook]
