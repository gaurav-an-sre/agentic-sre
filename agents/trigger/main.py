"""The human-facing bridge to the agent squad, one small Cloud Run service:

  POST /pagerduty        PagerDuty webhook -> start a v2 investigation on Agent Engine
  GET  /proposals/{id}   read a proposal (the human's preview before approving)
  POST /approve          {proposal_id, approver} + X-Approve-Token -> write the approval record
  GET  /health

The approval path is a human action, not a model action: it writes the record the control plane and
remediation-mcp check, in the shared proposal store (PROPOSAL_STORE=gcs in the cloud deployment).
Wire /approve into a Slack slash command or a button; the token lives in Secret Manager.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from datetime import UTC, datetime

import proposals as store
import vertexai
from fastapi import FastAPI, Header, HTTPException, Request
from vertexai import agent_engines

app = FastAPI()
SECRET = os.environ.get("PAGERDUTY_WEBHOOK_SECRET", "")
APPROVE_TOKEN = os.environ.get("APPROVE_TOKEN", "")


def _log(msg: str, **fields: object) -> None:
    print(json.dumps({"severity": "INFO", "message": msg, **fields}), file=sys.stdout, flush=True)


def _verify(body: bytes, signature_header: str) -> bool:
    expected = "v1=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s.strip()) for s in signature_header.split(","))


@app.post("/pagerduty")
async def pagerduty(req: Request, x_pagerduty_signature: str = Header(default="")) -> dict:
    body = await req.body()
    if not SECRET or not _verify(body, x_pagerduty_signature):
        raise HTTPException(401, "bad signature")
    ev = (await req.json()).get("event", {})
    if ev.get("event_type") != "incident.triggered":
        return {"ignored": ev.get("event_type")}
    inc = ev.get("data", {})
    page = f"PagerDuty {inc.get('incident_number')} [{inc.get('urgency')}]: {inc.get('title')} ({inc.get('html_url')})"
    vertexai.init(project=os.environ["PROJECT"], location=os.environ.get("REGION", "asia-southeast1"))
    engine = agent_engines.get(os.environ["AGENT_ENGINE_ID"])
    session = engine.create_session(user_id="pagerduty")
    events = [e for e in engine.stream_query(user_id="pagerduty", session_id=session["id"], message=page)]
    return {"session": session["id"], "events": len(events), "page": page}


@app.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str, x_approve_token: str = Header(default="")) -> dict:
    if not APPROVE_TOKEN or not hmac.compare_digest(APPROVE_TOKEN, x_approve_token):
        raise HTTPException(401, "bad approve token")
    rec = store.load(proposal_id)
    if rec is None:
        raise HTTPException(404, "unknown proposal")
    return rec


@app.post("/approve")
async def approve(req: Request, x_approve_token: str = Header(default="")) -> dict:
    if not APPROVE_TOKEN or not hmac.compare_digest(APPROVE_TOKEN, x_approve_token):
        raise HTTPException(401, "bad approve token")
    body = await req.json()
    pid, who = str(body.get("proposal_id", "")), str(body.get("approver", "unknown"))
    rec = store.load(pid)
    if rec is None:
        raise HTTPException(404, "unknown proposal")
    if rec["status"] != "pending_approval":
        raise HTTPException(409, f"proposal is '{rec['status']}', only pending_approval can be approved")
    rec.update(status="approved", approved_by=who, approved_ts=datetime.now(UTC).isoformat())
    store.save(rec)
    _log("Approve", proposal=pid, by=who)
    return rec


@app.get("/health")
def health() -> dict:
    return {"ok": True}
