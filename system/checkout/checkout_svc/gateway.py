"""Payment provider. Two modes:

  local (no PAYMENTS_URL): deterministic simulation - declines when the request doesn't match the
      checkout's own arithmetic (the promo-mismatch incident).
  http  (PAYMENTS_URL set): real call to the payments-api Cloud Run service, propagating the
      shopper's X-Request-ID so one click is traceable storefront -> checkout -> payments-api.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import httpx

PAYMENTS_URL = os.environ.get("PAYMENTS_URL", "").rstrip("/")


def authorize(
    request: dict[str, Any], reconciliation_total_cents: int, request_id: str = ""
) -> dict[str, Any]:
    requested = int(request["amount_cents"])
    out = {"requested_amount_cents": requested,
           "reconciliation_amount_cents": reconciliation_total_cents}
    # the checkout's own arithmetic guard runs before any provider call: a cart whose
    # authorization request doesn't match the quote never reaches the PSP
    if requested != reconciliation_total_cents:
        return {"decision": "declined", "reason": "amount_mismatch", **out}
    if PAYMENTS_URL:
        return _authorize_remote(requested, request_id, out)
    return {"decision": "approved", "reason": None, **out}


def _authorize_remote(requested: int, request_id: str, out: dict[str, Any]) -> dict[str, Any]:
    """Call payments-api POST /v1/transfers. Any failure is a decline, never a silent success."""
    headers = {"X-Request-ID": request_id} if request_id else {}
    try:
        resp = httpx.post(
            f"{PAYMENTS_URL}/v1/transfers",
            json={"from_account": "acc_0001", "to_account": "acc_0002",
                  "amount": str(round(requested / 100, 2)), "currency": "SGD",
                  "idempotency_key": request_id or f"chk_{uuid.uuid4().hex[:12]}"},
            headers=headers, timeout=15)
    except httpx.HTTPError:
        return {"decision": "declined", "reason": "psp_unreachable", **out}
    if resp.status_code < 300:
        return {"decision": "approved", "reason": None,
                "transfer_id": resp.json().get("transfer_id"), **out}
    reason = {422: "insufficient_funds", 503: "psp_unavailable"}.get(
        resp.status_code, f"psp_http_{resp.status_code}")
    return {"decision": "declined", "reason": reason, "psp_status": resp.status_code, **out}
