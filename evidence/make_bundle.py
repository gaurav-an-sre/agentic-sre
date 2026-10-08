"""Build the frozen evidence bundle for incident INC-2026-1009 (deterministic, synthetic).

Scenario: payments-api (Cloud Run, asia-southeast1). Deploy v2.14.3 at 09:12Z shipped a config change
DB_POOL_SIZE 50 -> 5. p95 latency and 5xx climb from 09:13; logs show pool exhaustion.
Red herring: cache-node-2 restarted at 09:05Z (unrelated, recovers by 09:08).
Wrong-fix trap: restarting Cloud Run instances clears errors for ~2 min then they return.
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "evidence" / "INC-2026-1009"
T0 = datetime(2026, 10, 9, 8, 30, tzinfo=UTC)
DEPLOY = datetime(2026, 10, 9, 9, 12, tzinfo=UTC)


def ts(i: int) -> str:
    return (T0 + timedelta(minutes=i)).isoformat().replace("+00:00", "Z")


def build() -> dict[str, str]:
    rng = random.Random(7)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "config").mkdir(exist_ok=True)
    (OUT / "runbooks").mkdir(exist_ok=True)
    n = 76  # 08:30 -> 09:45

    def series(svc: str, metric: str, f) -> dict:
        return {"service": svc, "metric": metric,
                "points": [{"ts": ts(i), "value": round(f(i), 3)} for i in range(n)]}

    after = lambda i: i >= 43  # noqa: E731  (09:13Z onwards)
    metrics = [
        series("payments-api", "http_p95_latency_ms",
               lambda i: 180 + rng.uniform(-15, 15) + (1900 + rng.uniform(-200, 200) if after(i) else 0)),
        series("payments-api", "http_5xx_rate",
               lambda i: 0.002 + rng.uniform(0, 0.002) + (0.18 + rng.uniform(-0.03, 0.03) if after(i) else 0)),
        series("payments-api", "db_pool_in_use",
               lambda i: (22 + rng.uniform(-4, 4)) if not after(i) else 5),
        series("payments-api", "db_pool_size", lambda i: 50 if i < 42 else 5),
        series("payments-api", "db_pool_wait_ms",
               lambda i: 2 + rng.uniform(0, 2) + (1400 + rng.uniform(-100, 100) if after(i) else 0)),
        series("payments-api", "cpu_pct", lambda i: 38 + rng.uniform(-5, 5) - (12 if after(i) else 0)),
        series("payments-db", "active_connections",
               lambda i: 24 + rng.uniform(-4, 4) if not after(i) else 5 + rng.uniform(0, 1)),
        series("payments-db", "cpu_pct", lambda i: 30 + rng.uniform(-4, 4) - (14 if after(i) else 0)),
        series("cache-node-2", "hit_rate",
               lambda i: 0.93 + rng.uniform(-0.01, 0.01) if not 35 <= i <= 38 else 0.0),
        series("ledger-svc", "http_p95_latency_ms", lambda i: 95 + rng.uniform(-8, 8)),
        series("ledger-svc", "http_5xx_rate", lambda i: 0.001 + rng.uniform(0, 0.001)),
    ]
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=1))

    logs = []
    lid = 0

    def log(i: int, svc: str, level: str, msg: str, **kw):
        nonlocal lid
        lid += 1
        logs.append({"id": f"L{lid:05d}", "ts": ts(i), "service": svc, "level": level,
                     "msg": msg, **kw})

    for i in range(n):
        if i % 3 == 0:
            log(i, "payments-api", "INFO", "health check ok", instance=f"payments-api-00042-{rng.randint(1, 4)}")
        if i == 35:
            log(i, "cache-node-2", "WARN", "node restarting: scheduled maintenance window")
        if i == 38:
            log(i, "cache-node-2", "INFO", "node ready, warming cache")
        if i == 42:
            log(i, "deployer", "INFO", "rollout started payments-api v2.14.3 (change CHG-88213)")
            log(i, "payments-api", "INFO", "config loaded: DB_POOL_SIZE=5 DB_POOL_TIMEOUT_MS=1500",
                instance="api-1", version="v2.14.3")
        if after(i):
            for _ in range(rng.randint(2, 4)):
                log(i, "payments-api", "ERROR",
                    f"PoolTimeout: connection pool exhausted (size=5, waiting={rng.randint(31, 88)}) "
                    "after 1500ms", instance=f"payments-api-00042-{rng.randint(1, 4)}", version="v2.14.3")
            if rng.random() < 0.3:
                log(i, "payments-api", "ERROR", "POST /v1/transfers -> 503 upstream_timeout",
                    instance=f"payments-api-00042-{rng.randint(1, 4)}")
        if i == 50:
            log(i, "oncall", "INFO", "manual action: restarted api-2 (errors cleared ~2 min, returned)")
    (OUT / "logs.jsonl").write_text("\n".join(json.dumps(x) for x in logs) + "\n")

    deployments = [
        {"id": "D-7725", "service": "payments-api", "version": "v2.14.2", "ts": ts(-1380),
         "revision": "payments-api-00041-kqd", "change": "CHG-88102",
         "summary": "last known good (yesterday)", "diff": []},
        {"id": "D-7731", "service": "ledger-svc", "version": "v1.9.0", "ts": ts(5),
         "revision": "ledger-svc-00017-bzt", "change": "CHG-88190", "summary": "dependency bumps", "diff": []},
        {"id": "D-7740", "service": "payments-api", "version": "v2.14.3", "ts": ts(42),
         "revision": "payments-api-00042-x7f", "change": "CHG-88213",
         "summary": "cost optimisation: right-size DB connection pool per instance",
         "diff": [{"file": "config/payments-api.env", "key": "DB_POOL_SIZE", "old": "50", "new": "5"},
                  {"file": "config/payments-api.env", "key": "DB_POOL_TIMEOUT_MS", "old": "5000",
                   "new": "1500"}]},
    ]
    (OUT / "deployments.json").write_text(json.dumps(deployments, indent=1))
    alerts = [
        {"id": "A-1", "ts": ts(37), "severity": "warning", "service": "cache-node-2",
         "name": "CacheHitRateLow", "status": "resolved", "resolved_ts": ts(39)},
        {"id": "A-2", "ts": ts(45), "severity": "critical", "service": "payments-api",
         "name": "HighErrorRate5xx", "status": "firing"},
        {"id": "A-3", "ts": ts(46), "severity": "critical", "service": "payments-api",
         "name": "P95LatencySLOBurn", "status": "firing"},
    ]
    (OUT / "alerts.json").write_text(json.dumps(alerts, indent=1))
    (OUT / "config" / "payments-api.env").write_text(
        "# payments-api runtime config (v2.14.3)\nDB_HOST=payments-db.internal\nDB_POOL_SIZE=5\n"
        "DB_POOL_TIMEOUT_MS=1500\nCACHE_URL=cache.internal:6379\nLOG_LEVEL=INFO\n")
    (OUT / "config" / "payments-api.env.previous").write_text(
        "# payments-api runtime config (v2.14.2)\nDB_HOST=payments-db.internal\nDB_POOL_SIZE=50\n"
        "DB_POOL_TIMEOUT_MS=5000\nCACHE_URL=cache.internal:6379\nLOG_LEVEL=INFO\n")
    (OUT / "runbooks" / "payments-api-rollback.md").write_text(
        "# Runbook: payments-api rollback\n1. Confirm the faulty deploy id and change ticket.\n"
        "2. `deployctl rollback payments-api --to <previous-version>` (requires approval from "
        "on-call lead).\n3. Watch http_5xx_rate and db_pool_wait_ms for 5 minutes.\n"
        "4. Open a postmortem.\n")
    (OUT / "incident.json").write_text(json.dumps({
        "id": "INC-2026-1009", "opened_ts": ts(47), "reporter": "pagerduty",
        "summary": "Customers report failed transfers; payments-api error rate elevated",
        "severity_guess": "SEV2", "window": {"from": ts(0), "to": ts(n - 1)}}, indent=1))

    manifest = {}
    for f in sorted(p for p in OUT.rglob("*") if p.is_file() and p.name != "manifest.json"):
        manifest[str(f.relative_to(OUT))] = hashlib.sha256(f.read_bytes()).hexdigest()
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


if __name__ == "__main__":
    m = build()
    print(f"bundle written to {OUT} ({len(m)} files, manifest sealed)")
