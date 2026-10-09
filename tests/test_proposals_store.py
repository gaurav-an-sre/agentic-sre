"""The proposal store is the shared record between the agent gate, remediation-mcp and the
human approve endpoint - local files offline, GCS in the cloud (PROPOSAL_STORE=gcs)."""
import pytest

from agents.common import control_plane as cp
from agents.common import proposals
from agents.common import tools as t


@pytest.fixture(autouse=True)
def store_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PROPOSALS_DIR", str(tmp_path))
    monkeypatch.setattr(cp, "AUDIT", tmp_path / "audit.jsonl")
    return tmp_path


def _pending(pid="P-test01"):
    proposals.save({"id": pid, "status": "pending_approval", "target_revision": "payments-api-00041-kqd"})
    return pid


def test_save_load_iter():
    pid = _pending()
    assert proposals.load(pid)["status"] == "pending_approval"
    assert proposals.load("P-nope") is None
    assert [r["id"] for r in proposals.iter_records()] == [pid]


def test_human_approval_persists_everywhere():
    pid = _pending()
    cp.approve(pid, "oncall@retailer")
    assert proposals.load(pid)["approved_by"] == "oncall@retailer"  # what remediation-mcp will see


def test_approve_unknown_proposal_is_an_error_not_a_crash():
    assert "error" in cp.approve("P-missing", "oncall@retailer")


def test_apply_simulated_marks_record_applied(store_dir):
    rec = t.propose_remediation("rollback", "rollback payments-api", "see D-7740",
                              ["D-7740"], "revert", "payments-api-00041-kqd")
    pid = rec["proposal_id"]
    cp.approve(pid, "oncall@retailer")
    t.apply_remediation(pid)
    assert proposals.load(pid)["status"] == "applied"
