"""v2 control plane: ADK callbacks that run around every tool call, independent of the model.

- audit: every tool call and result -> audit/tool_calls.jsonl (one line each)
- policy gate: apply_remediation / shift_traffic are denied unless the proposal file says "approved"
- red button: both are denied while audit/RED_BUTTON exists or AGENT_ACTUATION_PAUSED=1
- citation gate: propose_remediation is denied if any evidence ref is not in the bundle
The model cannot talk its way past these; they are plain Python, not prompt text.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from google.adk.tools import BaseTool, ToolContext

from agents.common import proposals
from agents.common.bundle import ROOT
from agents.common.tools import validate_citations

AUDIT = ROOT / "audit" / "tool_calls.jsonl"


def audit(event: str, **fields: Any) -> None:
    AUDIT.parent.mkdir(exist_ok=True)
    with AUDIT.open("a") as f:
        f.write(json.dumps({"ts": datetime.now(UTC).isoformat(), "event": event, **fields}, default=str) + "\n")


def before_tool(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> dict | None:
    """Return a dict to SHORT-CIRCUIT the tool (ADK uses it as the tool result); None to allow."""
    audit("PreToolUse", agent=tool_context.agent_name, tool=tool.name, args=args)
    if tool.name in {"apply_remediation", "shift_traffic"}:
        from mcp_servers.safety import red_button
        if (stop := red_button()) and not args.get("dry_run"):
            audit("PolicyDeny", tool=tool.name, reason=stop)
            return {"denied": True, "reason": stop}
        pid = str(args.get("proposal_id", ""))
        rec = proposals.load(pid)
        status = rec["status"] if rec else "unknown"
        if status != "approved":
            audit("PolicyDeny", tool=tool.name, proposal=pid, status=status)
            return {"denied": True, "reason": f"policy: proposal {pid} status is '{status}'; "
                                              "a human must approve before any remediation runs."}
    if tool.name == "propose_remediation":
        bad = validate_citations(list(args.get("evidence_refs") or []))
        if bad or not args.get("evidence_refs"):
            audit("CitationDeny", tool=tool.name, bad_refs=bad)
            return {"denied": True, "reason": f"citation validator: unknown evidence refs {bad}; "
                                              "cite ids returned by get_logs/get_recent_deployments/get_alerts."}
    return None


def after_tool(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, tool_response: Any) -> None:
    audit("PostToolUse", agent=tool_context.agent_name, tool=tool.name,
          response_chars=len(json.dumps(tool_response, default=str)))


def approve(proposal_id: str, approver: str) -> dict:
    """Human step. No model involved: writes the approval record the policy gate looks for."""
    rec = proposals.load(proposal_id)
    if rec is None:
        return {"error": f"unknown proposal {proposal_id}"}
    rec.update(status="approved", approved_by=approver, approved_ts=datetime.now(UTC).isoformat())
    proposals.save(rec)
    audit("Approve", proposal=proposal_id, by=approver)
    return rec
