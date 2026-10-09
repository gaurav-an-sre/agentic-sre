"""payments-api: minimal transfers service for the live SRE demo (Cloud Run + Cloud SQL Postgres).

Every request borrows a connection from a pool sized by DB_POOL_SIZE. A deploy that shrinks the
pool makes POST /v1/transfers queue on the pool, time out after DB_POOL_TIMEOUT_MS and return 503 -
the same failure mode as the frozen bundle INC-2026-1009, but real.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, PoolTimeout
from pydantic import BaseModel, Field

VERSION = os.environ.get("APP_VERSION", "dev")
POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "50"))
POOL_TIMEOUT_MS = int(os.environ.get("DB_POOL_TIMEOUT_MS", "5000"))
LEDGER_WRITE_MS = int(os.environ.get("LEDGER_WRITE_MS", "300"))  # simulated ledger fan-out work
REVISION = os.environ.get("K_REVISION", "local")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"severity": record.levelname, "message": record.getMessage(),
                   "service": "payments-api", "version": VERSION, "revision": REVISION}
        extra = getattr(record, "fields", None)
        if extra:
            payload.update(extra)
        return json.dumps(payload)


handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
log = logging.getLogger("payments-api")
log.handlers = [handler]
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
log.propagate = False


def _log(level: int, msg: str, **fields: object) -> None:
    log.log(level, msg, extra={"fields": fields})


def dsn() -> str:
    if "DATABASE_URL" in os.environ:
        return os.environ["DATABASE_URL"]
    host = os.environ.get("DB_HOST", "localhost")  # Cloud Run: /cloudsql/<connection-name>
    return (f"host={host} dbname={os.environ.get('DB_NAME', 'payments')} "
            f"user={os.environ.get('DB_USER', 'payments')} password={os.environ.get('DB_PASSWORD', '')}")


pool = AsyncConnectionPool(dsn(), min_size=1, max_size=POOL_SIZE, timeout=POOL_TIMEOUT_MS / 1000,
                           open=False, kwargs={"row_factory": dict_row})


@asynccontextmanager
async def lifespan(_: FastAPI):
    await pool.open()
    _log(logging.INFO, f"config loaded: DB_POOL_SIZE={POOL_SIZE} DB_POOL_TIMEOUT_MS={POOL_TIMEOUT_MS}",
         db_pool_size=POOL_SIZE, db_pool_timeout_ms=POOL_TIMEOUT_MS)
    yield
    await pool.close()


app = FastAPI(title="payments-api", version=VERSION, lifespan=lifespan)


class TransferIn(BaseModel):
    from_account: str
    to_account: str
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = "SGD"
    idempotency_key: str | None = None


@app.middleware("http")
async def access_log(request: Request, call_next):
    t0 = time.perf_counter()
    rid = request.headers.get("x-request-id") or f"req_{uuid.uuid4().hex[:12]}"
    try:
        resp = await call_next(request)
    except Exception as exc:  # noqa: BLE001 - last-resort guard so the access log line is still emitted
        _log(logging.ERROR, f"{request.method} {request.url.path} -> 500 {type(exc).__name__}: {exc}",
             latency_ms=round((time.perf_counter() - t0) * 1000, 1), status=500,
             error=type(exc).__name__, request_id=rid)
        return JSONResponse({"error": "internal"}, status_code=500)
    ms = round((time.perf_counter() - t0) * 1000, 1)
    stats = pool.get_stats()
    level = logging.ERROR if resp.status_code >= 500 else logging.INFO
    _log(level, f"{request.method} {request.url.path} -> {resp.status_code}", status=resp.status_code,
         latency_ms=ms, request_id=rid,
         db_pool_in_use=stats.get("pool_size", 0) - stats.get("pool_available", 0),
         db_pool_size=POOL_SIZE, db_pool_waiting=stats.get("requests_waiting", 0))
    resp.headers["X-Request-ID"] = rid
    return resp


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": VERSION, "revision": REVISION, "db_pool_size": POOL_SIZE}


@app.get("/v1/accounts/{account_id}")
async def get_account(account_id: str) -> dict:
    try:
        async with pool.connection() as conn:
            row = await (await conn.execute(
                "SELECT account_id, balance, currency FROM accounts WHERE account_id=%s", (account_id,))
            ).fetchone()
    except PoolTimeout as exc:
        raise _pool_exhausted(exc) from exc
    if not row:
        raise HTTPException(404, "account not found")
    return {**row, "balance": str(row["balance"])}


@app.post("/v1/transfers", status_code=201)
async def create_transfer(body: TransferIn) -> dict:
    tid = body.idempotency_key or f"tr_{uuid.uuid4().hex[:12]}"
    try:
        async with pool.connection() as conn:
            existing = await (await conn.execute(
                "SELECT transfer_id, amount, currency FROM transfers WHERE transfer_id=%s", (tid,))
            ).fetchone()
        if existing:
            return {"transfer_id": existing["transfer_id"], "status": "settled",
                    "amount": str(existing["amount"]), "currency": existing["currency"],
                    "idempotent_replay": True}
        async with pool.connection() as conn, conn.transaction():
            src = await (await conn.execute(
                "SELECT balance FROM accounts WHERE account_id=%s FOR UPDATE", (body.from_account,))
            ).fetchone()
            if not src:
                raise HTTPException(404, "from_account not found")
            if src["balance"] < body.amount:
                raise HTTPException(422, "insufficient funds")
            await conn.execute("UPDATE accounts SET balance=balance-%s WHERE account_id=%s",
                               (body.amount, body.from_account))
            await conn.execute("UPDATE accounts SET balance=balance+%s WHERE account_id=%s",
                               (body.amount, body.to_account))
            await conn.execute(
                "INSERT INTO transfers(transfer_id, from_account, to_account, amount, currency) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (transfer_id) DO NOTHING",
                (tid, body.from_account, body.to_account, body.amount, body.currency))
            # ledger fan-out holds the connection for a bit; this is what makes a small pool hurt
            await conn.execute("SELECT pg_sleep(%s)", (LEDGER_WRITE_MS / 1000,))
    except PoolTimeout as exc:
        raise _pool_exhausted(exc) from exc
    return {"transfer_id": tid, "status": "settled", "amount": str(body.amount), "currency": body.currency}


def _pool_exhausted(exc: PoolTimeout) -> HTTPException:
    waiting = pool.get_stats().get("requests_waiting", 0)
    _log(logging.ERROR,
         f"PoolTimeout: connection pool exhausted (size={POOL_SIZE}, waiting={waiting}) "
         f"after {POOL_TIMEOUT_MS}ms",
         error="PoolTimeout", db_pool_size=POOL_SIZE, db_pool_waiting=waiting)
    return HTTPException(503, "upstream_timeout: db pool exhausted")
