"""Pre-flight checks on the production write path, below the model and independent of it.

Added after the first live denial showed that a binary approval gate is not enough: the on-caller had no
preview of blast radius, and nothing stopped two remediations from racing each other or a rollback from
landing in the middle of a promo peak. These are the controls Google SRE's AI-ops paper calls dry-run,
justification verification, concurrent-action check and the "Red Button".

    red_button()        -> every agent actuation is paused (env AGENT_ACTUATION_PAUSED=1 or file audit/RED_BUTTON)
    justification()     -> the action must reference the open incident the page belongs to
    concurrent_action() -> another proposal was applied inside the last CONCURRENT_WINDOW_MIN minutes
    change_freeze()     -> local hour inside CHANGE_FREEZE_HOURS (e.g. "18-23" for promo nights)

Checks never mutate anything; the caller decides deny / hold / proceed and audits the outcome.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from agents.common import proposals as proposal_store
from agents.common import tools as bundle_tools
from agents.common.bundle import ROOT

RED_BUTTON_FILE = ROOT / "audit" / "RED_BUTTON"


def red_button() -> str | None:
    if os.environ.get("AGENT_ACTUATION_PAUSED", "") in {"1", "true", "on"}:
        return "red button: AGENT_ACTUATION_PAUSED is set; all agent actuation is paused"
    if RED_BUTTON_FILE.exists():
        return f"red button: {RED_BUTTON_FILE.name} present ({RED_BUTTON_FILE.read_text().strip() or 'no reason given'})"
    return None


def justification(incident_id: str) -> str | None:
    inc = bundle_tools.bundle.incident()
    if not incident_id:
        return "justification: no incident_id; a production change must reference the open incident"
    if incident_id != inc["id"]:
        return f"justification: incident {incident_id} is not the open incident ({inc['id']})"
    if inc.get("resolved_ts"):
        return f"justification: incident {incident_id} is already resolved"
    return None


def concurrent_action(proposal_id: str, proposals: Path | None = None) -> str | None:
    window = timedelta(minutes=int(os.environ.get("CONCURRENT_WINDOW_MIN", "10")))
    now = datetime.now(UTC)
    if proposals is not None:
        records = (json.loads(p.read_text()) for p in proposals.glob("P-*.json"))
    else:
        records = proposal_store.iter_records()
    for rec in records:
        if rec.get("id") == proposal_id:
            continue
        if rec.get("status") != "applied" or not rec.get("applied_ts"):
            continue
        age = now - datetime.fromisoformat(rec["applied_ts"])
        if age < window:
            return f"concurrent action: {rec.get('id')} was applied {int(age.total_seconds())}s ago"
    return None


def change_freeze(now: datetime | None = None) -> str | None:
    spec = os.environ.get("CHANGE_FREEZE_HOURS", "")
    if not spec:
        return None
    start, end = (int(x) for x in spec.split("-"))
    hour = (now or datetime.now(ZoneInfo(os.environ.get("LOCAL_TZ", "Asia/Bangkok")))).hour
    if start <= hour < end:
        return f"change freeze: local hour {hour} is inside {spec}"
    return None


def pre_flight(proposal_id: str, incident_id: str) -> dict:
    """Everything that can stop or hold an actuation, in one record the on-caller can read."""
    deny = red_button() or justification(incident_id)
    hold = [h for h in (concurrent_action(proposal_id), change_freeze()) if h]
    return {"deny": deny, "holds": hold}
