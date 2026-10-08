"""A deterministic payment provider simulation."""

from __future__ import annotations

from typing import Any


def authorize(
    request: dict[str, Any], reconciliation_total_cents: int
) -> dict[str, Any]:
    requested = int(request["amount_cents"])
    if requested != reconciliation_total_cents:
        return {
            "decision": "declined",
            "reason": "amount_mismatch",
            "requested_amount_cents": requested,
            "reconciliation_amount_cents": reconciliation_total_cents,
        }
    return {
        "decision": "approved",
        "reason": None,
        "requested_amount_cents": requested,
        "reconciliation_amount_cents": reconciliation_total_cents,
    }
