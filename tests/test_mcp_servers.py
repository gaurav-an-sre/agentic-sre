"""MCP servers in bundle mode (offline): same records as the in-process tools, remediation gated."""

from __future__ import annotations

import asyncio
import json

import pytest

from agents.common import tools as t
from agents.common.control_plane import approve
from mcp_servers import incident, observability, release, remediation


def test_servers_expose_expected_tools() -> None:
    names = {s.name: {x.name for x in asyncio.run(s.list_tools())} for s in
             (observability.server, release.server, incident.server, remediation.server)}
    assert {"query_metrics", "get_alerts", "get_logs", "get_slo", "get_service_health"} <= names["observability-mcp"]
    assert {"list_revisions", "get_deploy_diff", "read_config", "get_runbook"} <= names["release-mcp"]
    assert {"get_incident", "create_issue", "write_postmortem"} <= names["incident-mcp"]
    assert names["remediation-mcp"] == {"shift_traffic"}  # exactly one production write


def test_read_tools_return_citeable_ids() -> None:
    logs = observability.get_logs("payments-api", "ERROR", 5)
    assert logs["count"] > 0 and all(l["id"].startswith("L") for l in logs["lines"])
    revs = release.list_revisions("payments-api")
    assert revs and all("id" in r for r in revs)
    assert "metric" in observability.query_metrics("payments-api", "http_5xx_rate")
    assert observability.get_slo("payments-api")["slo_target"] == 0.995


def test_shift_traffic_denied_without_approval(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PROPOSALS_DIR", str(tmp_path))
    good = next(d["revision"] for d in t.bundle.deployments() if d.get("revision"))
    res = remediation.shift_traffic("P-nope", "payments-api", good)
    assert res["denied"] and "not approved" in res["reason"]


def test_shift_traffic_requires_matching_allowlisted_revision(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PROPOSALS_DIR", str(tmp_path))
    revs = [d["revision"] for d in t.bundle.deployments() if d.get("revision")]
    target = revs[0]
    pid = t.propose_remediation("rb", "rollback", "why", [t.bundle.deployments()[-1]["id"]], "redeploy", target)["proposal_id"]
    inc = t.bundle.incident()["id"]
    assert remediation.shift_traffic(pid, "payments-api", target, incident_id=inc)["denied"]  # pending
    approve(pid, "oncall@example.com")
    assert remediation.shift_traffic(pid, "payments-api", "payments-api-99999-zzz", incident_id=inc)["denied"]  # wrong target
    ok = remediation.shift_traffic(pid, "payments-api", target, incident_id=inc)
    assert "simulated" in ok["result"]
    assert json.loads((tmp_path / f"{pid}.json").read_text())["status"] == "applied"


def test_incident_writes_stay_local_without_jira(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("JIRA_SITE", raising=False)
    monkeypatch.setattr(incident, "LOCAL", tmp_path)
    res = incident.create_issue("pool-size guard in CI", "add check")
    assert res["key"].startswith("LOCAL-")


@pytest.mark.parametrize("name", ["observability", "release", "incident", "remediation"])
def test_streamable_http_app_builds(name: str) -> None:
    import importlib
    assert importlib.import_module(f"mcp_servers.{name}").server.streamable_http_app() is not None
