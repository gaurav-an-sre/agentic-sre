"""Offline tests: no API key, no GCP. The control plane must hold with zero model involvement."""

import json
from types import SimpleNamespace

import pytest

from agents.common import control_plane as cp
from agents.common import tools as t
from agents.v2.agent import root_agent

CTX = SimpleNamespace(agent_name="test")


@pytest.fixture(autouse=True)
def _tmp_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("PROPOSALS_DIR", str(tmp_path / "proposals"))
    monkeypatch.setattr(cp, "AUDIT", tmp_path / "audit.jsonl")


def _tool(name):
    return SimpleNamespace(name=name)


def test_bundle_sealed():
    assert t.verify_bundle()["integrity"]["ok"]


def test_proposal_rejects_unknown_evidence():
    r = t.propose_remediation("x", "rollback", "why", ["L99999", "made-up"], "n/a")
    assert "citation check failed" in r["error"]


def test_proposal_then_apply_is_gated_until_human_approves():
    dep = t.get_recent_deployments()
    bad_dep = next(d for d in dep if "5" in json.dumps(d.get("diff", d)))
    r = t.propose_remediation("rollback", "shift traffic", "pool shrank", [bad_dep["id"]], "redeploy",
                              target_revision="payments-api-00041-kqd")
    pid = r["proposal_id"]
    denied = cp.before_tool(_tool("apply_remediation"), {"proposal_id": pid}, CTX)
    assert denied and denied["denied"] and "pending_approval" in denied["reason"]
    assert t.apply_remediation(pid)["error"].endswith("not approved")  # tool itself also refuses
    cp.approve(pid, "oncall-lead")
    assert cp.before_tool(_tool("apply_remediation"), {"proposal_id": pid}, CTX) is None
    out = t.apply_remediation(pid)
    assert out["proposal"] == pid and "simulated" in out["result"]
    events = [json.loads(l)["event"] for l in cp.AUDIT.read_text().splitlines()]
    assert events == ["PreToolUse", "PolicyDeny", "Approve", "PreToolUse"]


def test_citation_gate_in_callback():
    r = cp.before_tool(_tool("propose_remediation"), {"evidence_refs": ["nope"]}, CTX)
    assert r["denied"] and "citation validator" in r["reason"]


def test_v1_has_no_gates_and_v2_has_them():
    from agents.v1.agent import root_agent as v1
    assert v1.before_tool_callback is None
    assert any(tl.__name__ == "apply_remediation_ungated" for tl in v1.tools)
    leaves = []
    stack = [root_agent]
    while stack:
        a = stack.pop()
        stack.extend(getattr(a, "sub_agents", []))
        if not getattr(a, "sub_agents", []):
            leaves.append(a)
    assert len(leaves) == 5
    assert all(a.before_tool_callback is cp.before_tool for a in leaves)
    assert not any(tl.__name__ == "apply_remediation" for a in leaves for tl in a.tools)


def test_gcp_rollback_only_to_known_revision():
    assert "not in the bundle" in t._rollback_cloud_run({"service": "s", "region": "r", "project": "p"}, "ghost")["error"]
