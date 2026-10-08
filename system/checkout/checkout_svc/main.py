"""FastAPI storefront and checkout API."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from payments.authorize_request import build_authorization_request

from . import db
from .evidence import MetricsRecorder, append_jsonl, read_jsonl
from .gateway import authorize
from .pricing import quote
from .watchdog import Watchdog, WatchdogThread

logger = logging.getLogger("checkout_svc")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
metrics = MetricsRecorder()
watchdog_thread: WatchdogThread | None = None


class CartItem(BaseModel):
    product_id: int
    quantity: int = Field(ge=1, le=20)


class CartRequest(BaseModel):
    items: list[CartItem] = Field(min_length=1)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _cart_items(request: CartRequest) -> list[dict[str, Any]]:
    catalog = db.product_map()
    result: list[dict[str, Any]] = []
    for item in request.items:
        product = catalog.get(item.product_id)
        if product is None:
            raise HTTPException(status_code=400, detail=f"unknown product {item.product_id}")
        result.append(
            {
                "product_id": item.product_id,
                "name": product["name"],
                "unit_price_cents": int(product["price_cents"]),
                "quantity": item.quantity,
            }
        )
    return result


def _status() -> dict[str, Any]:
    now = datetime.now(UTC)
    orders = read_jsonl("orders.jsonl")
    recent = [
        order
        for order in orders
        if now
        - datetime.fromisoformat(str(order["timestamp"]).replace("Z", "+00:00"))
        <= timedelta(seconds=60)
    ]
    succeeded = sum(order["outcome"] == "succeeded" for order in recent)
    declined = sum(order["outcome"] == "declined" for order in recent)
    attempts = succeeded + declined
    buckets: list[dict[str, Any]] = []
    current_second = int(time.time())
    for offset in range(17, -1, -1):
        bucket_end = current_second - offset * 10
        bucket_start = bucket_end - 10
        bucket = [
            order
            for order in orders
            if bucket_start
            <= int(
                datetime.fromisoformat(str(order["timestamp"]).replace("Z", "+00:00")).timestamp()
            )
            < bucket_end
        ]
        bucket_attempts = len(bucket)
        buckets.append(
            {
                "start_second": bucket_start,
                "attempts": bucket_attempts,
                "success_rate": (
                    sum(order["outcome"] == "succeeded" for order in bucket) / bucket_attempts
                    if bucket_attempts
                    else None
                ),
            }
        )
    return {
        "succeeded_last_60s": succeeded,
        "declined_last_60s": declined,
        "attempts_last_60s": attempts,
        "success_rate": succeeded / attempts if attempts else None,
        "state": (
            "NO_TRAFFIC"
            if not attempts
            else "GREEN"
            if succeeded / attempts >= 0.90
            else "RED"
        ),
        "buckets": buckets,
    }


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global watchdog_thread
    db.initialize()
    watchdog_thread = WatchdogThread(Watchdog())
    watchdog_thread.start()
    try:
        yield
    finally:
        if watchdog_thread is not None:
            watchdog_thread.stop()
            watchdog_thread = None
        metrics.flush()


app = FastAPI(title="Storefront Incident Demo", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
def storefront(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="storefront.html",
        context={"products": db.products()},
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(content=b"", media_type="image/x-icon")


@app.get("/api/products")
def product_list() -> list[dict[str, Any]]:
    return db.products()


@app.post("/api/quote")
def quote_cart(cart_request: CartRequest) -> dict[str, Any]:
    items = _cart_items(cart_request)
    return quote(items).as_dict()


@app.post("/api/checkout")
def checkout(cart_request: CartRequest) -> dict[str, Any]:
    started = time.perf_counter()
    items = _cart_items(cart_request)
    customer_quote = quote(items)
    authorization = build_authorization_request(items)
    result = authorize(authorization, customer_quote.total_cents)
    outcome = "succeeded" if result["decision"] == "approved" else "declined"
    reason = result["reason"]
    timestamp = _timestamp()
    order_id = db.create_order(timestamp, outcome, reason, customer_quote.total_cents)
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    append_jsonl(
        "payments.jsonl",
        {
            "timestamp": timestamp,
            "order_id": order_id,
            "requested_amount_cents": result["requested_amount_cents"],
            "reconciliation_amount_cents": result["reconciliation_amount_cents"],
            "decision": result["decision"],
            "reason": reason,
        },
    )
    append_jsonl(
        "orders.jsonl",
        {
            "order_id": order_id,
            "timestamp": timestamp,
            "line_items": items,
            "quote": customer_quote.as_dict(),
            "authorized_amount_cents": result["requested_amount_cents"],
            "outcome": outcome,
            "decline_reason": reason,
            "latency_ms": latency_ms,
        },
    )
    metrics.record(outcome, latency_ms)
    if outcome == "declined":
        logger.warning("payment declined for order %s reason=%s", order_id, reason)
    return {
        "status": outcome,
        "order_id": order_id,
        "quote": customer_quote.as_dict(),
        "authorized_amount_cents": result["requested_amount_cents"],
        "decline_reason": reason,
    }


@app.get("/api/status")
def status() -> dict[str, Any]:
    return _status()
