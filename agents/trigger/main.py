"""PagerDuty webhook -> v2 squad on Agent Engine. Verifies the PagerDuty v3 signature, then starts a
session with the page text. Nothing else: the agent squad and its control plane do the work."""

from __future__ import annotations

import hashlib
import hmac
import os

import vertexai
from fastapi import FastAPI, Header, HTTPException, Request
from vertexai import agent_engines

app = FastAPI()
SECRET = os.environ.get("PAGERDUTY_WEBHOOK_SECRET", "")


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


@app.get("/health")
def health() -> dict:
    return {"ok": True}
