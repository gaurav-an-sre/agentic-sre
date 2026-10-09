"""storefront: the public edge of the demo shop. Serves the catalog page, forwards cart checkouts to the
checkout service, and is where X-Request-ID starts when the caller didn't bring one - so a single
shopper click shows up as one id in Cloud Logging across storefront -> checkout -> payments-api."""

from __future__ import annotations

import html
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

UPSTREAM = os.environ.get("CHECKOUT_URL", "http://localhost:8000").rstrip("/")
STATIC = Path(__file__).parent / "static"
app = FastAPI(title="storefront")
INDEX = (STATIC / "index.html").read_text()


def _log(level: int, msg: str, **fields: object) -> None:
    print(json.dumps({"severity": logging.getLevelName(level), "message": msg, **fields}),
          file=sys.stdout, flush=True)


@app.middleware("http")
async def access_log(request: Request, call_next):
    t0 = time.perf_counter()
    rid = request.headers.get("x-request-id") or f"req_{uuid.uuid4().hex[:12]}"
    request.state.request_id = rid
    resp = await call_next(request)
    _log(logging.INFO if resp.status_code < 500 else logging.ERROR,
         f"{request.method} {request.url.path} -> {resp.status_code}",
         status=resp.status_code, latency_ms=round((time.perf_counter() - t0) * 1000, 1),
         request_id=rid)
    resp.headers["X-Request-ID"] = rid
    return resp


def get_products() -> list[dict[str, Any]]:
    return httpx.get(f"{UPSTREAM}/api/products", timeout=10).json()


def post_checkout(payload: dict[str, Any], rid: str) -> httpx.Response:
    """The one call that matters for the demo: checkout downstream with the request id attached."""
    return httpx.post(f"{UPSTREAM}/api/checkout", json=payload,
                      headers={"X-Request-ID": rid}, timeout=15)


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> str:
    # the page shows its own request id via a meta tag - it is caller-influenced input, so
    # it goes through html.escape before rendering (XSS guard on a reflected header)
    rid = html.escape(getattr(request.state, "request_id", ""), quote=True)
    return INDEX.replace("</head>", f'<meta name="x-req" content="{rid}"></head>')


@app.get("/api/products")
def products() -> Any:
    try:
        return get_products()
    except httpx.HTTPError as exc:
        return JSONResponse({"status": "error", "reason": "catalog_unreachable",
                             "detail": str(exc)}, status_code=502)


@app.post("/api/checkout")
async def checkout(request: Request) -> JSONResponse:
    rid = getattr(request.state, "request_id", f"req_{uuid.uuid4().hex[:12]}")
    try:
        resp = post_checkout(await request.json(), rid)
    except httpx.HTTPError as exc:
        return JSONResponse({"status": "error", "reason": "checkout_unreachable",
                             "request_id": rid, "detail": str(exc)}, status_code=502)
    return JSONResponse(resp.json(), status_code=resp.status_code)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "upstream": UPSTREAM}


app.mount("/static", StaticFiles(directory=STATIC), name="static")
