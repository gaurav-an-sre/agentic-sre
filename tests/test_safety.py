"""Pre-flight controls on the one production write path, offline: dry-run, justification, red button, holds."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from agents.common import control_plane as cp
from agents.common import tools as t
from agents.common.control_plane import approve
from mcp_servers import remediation, safety

INC = t.bundle.incident()["id"]


@pytest.fixture
def approved(tmp_path, monkeypatch):
    monkeypatch.setenv("PROPOSALS_DIR", str(tmp_path))
    monkeypatch.setattr(cp, "AUDIT", tmp_path / "audit.jsonl")
    monkeypatch.setattr(safety, "RED_BUTTON_FILE", tmp_path / "RED_BUTTON")
    monkeypatch.delenv("AGENT_ACTUATION_PAUSED", raising=False)
    monkeypatch.delenv("CHANGE_FREEZE_HOURS", raising=False)
    target = next(d["revision"] for d in t.bundle.deployments() if d.get("revision"))
    pid = t.propose_remediation("rb", "rollback", "why", [t.bundle.deployments()[-1]["id"]], "redeploy", target)["proposal_id"]
    approve(pid, "oncall@example.com")
    return pid, target, tmp_path


def test_dry_run_changes_nothing(approved):
    pid, target, d = approved
    res = remediation.shift_traffic(pid, "payments-api", target, incident_id=INC, dry_run=True)
    assert res["dry_run"] and res["would_apply"] and res["plan"]["to"] == {target: 100}
    assert json.loads((d / f"{pid}.json").read_text())["status"] == "approved"  # still not applied


def test_justification_requires_open_incident(approved):
    pid, target, _ = approved
    assert "justification" in remediation.shift_traffic(pid, "payments-api", target)["reason"]
    assert "not the open incident" in remediation.shift_traffic(pid, "payments-api", target, incident_id="INC-0000")["reason"]


def test_red_button_pauses_everything(approved, monkeypatch):
    pid, target, _ = approved
    safety.RED_BUTTON_FILE.write_text("promo night, humans only")
    res = remediation.shift_traffic(pid, "payments-api", target, incident_id=INC)
    assert res["denied"] and "red button" in res["reason"]
    # the agent-side callback refuses too, before the call leaves the agent
    from types import SimpleNamespace
    out = cp.before_tool(SimpleNamespace(name="shift_traffic"), {"proposal_id": pid}, SimpleNamespace(agent_name="applier"))
    assert out["denied"] and "red button" in out["reason"]
    safety.RED_BUTTON_FILE.unlink()
    monkeypatch.setenv("AGENT_ACTUATION_PAUSED", "1")
    assert remediation.shift_traffic(pid, "payments-api", target, incident_id=INC)["denied"]


def test_concurrent_action_holds_until_human_overrides(approved):
    pid, target, d = approved
    other = {"id": "P-other", "status": "applied", "applied_ts": (datetime.now(UTC) - timedelta(minutes=2)).isoformat()}
    (d / "P-other.json").write_text(json.dumps(other))
    held = remediation.shift_traffic(pid, "payments-api", target, incident_id=INC)
    assert held["held"] and "concurrent action" in held["reason"]
    ok = remediation.shift_traffic(pid, "payments-api", target, incident_id=INC, override_hold="oncall@example.com")
    assert "simulated" in ok["result"]
    assert json.loads((d / f"{pid}.json").read_text())["override_hold"] == "oncall@example.com"


def test_change_freeze_hold(approved, monkeypatch):
    pid, target, _ = approved
    monkeypatch.setenv("CHANGE_FREEZE_HOURS", "0-24")
    assert "change freeze" in remediation.shift_traffic(pid, "payments-api", target, incident_id=INC)["reason"]
