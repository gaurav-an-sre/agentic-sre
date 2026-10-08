"""Snapshot a live Cloud Run incident into a frozen evidence bundle (same layout as the synthetic one).

  uv run python -m sre_agent.gcp snapshot --project P --service payments-api --region R [--minutes 45]

Reads Cloud Monitoring (built-in Cloud Run metrics), Cloud Logging (the service's JSON logs) and the
Cloud Run revision history, writes evidence/INC-<ts>/, seals a SHA-256 manifest and prints the
`export SRE_BUNDLE=...` line. Investigation then runs over an immutable snapshot, so every citation the
agent makes (L00042, D-<revision>) is verifiable after the fact. Auth = gcloud ADC / active account.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sre_agent.bundle import ROOT

MON = "https://monitoring.googleapis.com/v3"
LOGS = "https://logging.googleapis.com/v2"
RUN = "https://run.googleapis.com/v2"


def _token() -> str:
    return subprocess.run(["gcloud", "auth", "print-access-token"], check=True,
                          capture_output=True, text=True).stdout.strip()


def _call(url: str, token: str, body: dict | None = None, project: str = "") -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {token}", "x-goog-user-project": project,
                                          "Content-Type": "application/json"},
                                 method="POST" if body else "GET")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def _iso(d: datetime) -> str:
    return d.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _series(project: str, token: str, mfilter: str, start: datetime, end: datetime,
            aligner: str, reducer: str = "REDUCE_SUM") -> list[tuple[str, float]]:
    q = (f"filter={urllib.request.quote(mfilter)}&interval.startTime={_iso(start)}&interval.endTime={_iso(end)}"
         f"&aggregation.alignmentPeriod=60s&aggregation.perSeriesAligner={aligner}"
         f"&aggregation.crossSeriesReducer={reducer}")
    pts: dict[str, float] = {}
    for ts in _call(f"{MON}/projects/{project}/timeSeries?{q}", token, project=project).get("timeSeries", []):
        for p in ts["points"]:
            v = p["value"]
            val = float(v.get("doubleValue", v.get("int64Value", 0)))
            pts[p["interval"]["endTime"]] = pts.get(p["interval"]["endTime"], 0.0) + val
    return sorted(pts.items())


def snapshot(project: str, service: str, region: str, minutes: int = 45, out: Path | None = None) -> Path:
    token = _token()
    end = datetime.now(UTC).replace(second=0, microsecond=0)
    start = end - timedelta(minutes=minutes)
    inc = "INC-" + end.strftime("%Y%m%d-%H%M")
    out = out or ROOT / "evidence" / inc
    out.mkdir(parents=True, exist_ok=True)
    (out / "config").mkdir(exist_ok=True)
    (out / "runbooks").mkdir(exist_ok=True)

    # ---- metrics (built-in Cloud Run + Cloud SQL) ----
    base = f'resource.type="cloud_run_revision" AND resource.labels.service_name="{service}"'
    minute_axis = [_iso(start + timedelta(minutes=i)) for i in range(1, minutes + 1)]

    def fill(pairs: list[tuple[str, float]], scale: float = 1.0) -> list[dict]:
        d = dict(pairs)
        return [{"ts": t, "value": round(d.get(t, 0.0) * scale, 3)} for t in minute_axis]

    req_all = _series(project, token, base + ' AND metric.type="run.googleapis.com/request_count"', start, end,
                      "ALIGN_RATE")
    req_5xx = _series(project, token, base + ' AND metric.type="run.googleapis.com/request_count" AND '
                      'metric.labels.response_code_class="5xx"', start, end, "ALIGN_RATE")
    p95 = _series(project, token, base + ' AND metric.type="run.googleapis.com/request_latencies"', start, end,
                  "ALIGN_PERCENTILE_95", "REDUCE_MAX")
    inst = _series(project, token, base + ' AND metric.type="run.googleapis.com/container/instance_count"',
                   start, end, "ALIGN_MAX")
    all_d, five_d = dict(req_all), dict(req_5xx)
    rate = [(t, (five_d.get(t, 0.0) / all_d[t]) if all_d.get(t) else 0.0) for t in all_d]
    sql = 'resource.type="cloudsql_database" AND metric.type="cloudsql.googleapis.com/database/'
    db_conn = _series(project, token, sql + 'postgresql/num_backends"', start, end, "ALIGN_MEAN")
    db_cpu = _series(project, token, sql + 'cpu/utilization"', start, end, "ALIGN_MEAN", "REDUCE_MEAN")
    metrics = [
        {"service": service, "metric": "http_rps", "points": fill(req_all)},
        {"service": service, "metric": "http_5xx_rate", "points": fill(rate)},
        {"service": service, "metric": "http_p95_latency_ms", "points": fill(p95)},
        {"service": service, "metric": "instances", "points": fill(inst)},
        {"service": "payments-db", "metric": "active_connections", "points": fill(db_conn)},
        {"service": "payments-db", "metric": "cpu_pct", "points": fill(db_cpu, 100)},
    ]
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1))

    # ---- logs (the service's own JSON lines; ids assigned in time order -> citeable) ----
    lf = (f'resource.type="cloud_run_revision" AND resource.labels.service_name="{service}" '
          f'AND timestamp>="{_iso(start)}" AND jsonPayload.message:*')
    entries: list[dict] = []
    body: dict[str, Any] = {"resourceNames": [f"projects/{project}"], "filter": lf,
                            "orderBy": "timestamp desc", "pageSize": 1000}
    while True:
        page = _call(f"{LOGS}/entries:list", token, body, project)
        entries += page.get("entries", [])
        if not page.get("nextPageToken") or len(entries) >= 4000:
            break
        body["pageToken"] = page["nextPageToken"]
    entries = entries[:4000][::-1]
    lines = []
    for i, e in enumerate(entries, 1):
        jp = e.get("jsonPayload", {})
        rec = {"id": f"L{i:05d}", "ts": e["timestamp"][:19] + "Z", "service": service,
               "level": e.get("severity", "DEFAULT"), "msg": jp.get("message", ""),
               "revision": e["resource"]["labels"].get("revision_name")}
        rec.update({k: v for k, v in jp.items() if k not in {"message", "severity", "service", "revision"}})
        lines.append(rec)
    (out / "logs.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")

    # ---- deployments = Cloud Run revisions with env diffs ----
    svc = _call(f"{RUN}/projects/{project}/locations/{region}/services/{service}", token, project=project)
    revs = _call(f"{RUN}/projects/{project}/locations/{region}/services/{service}/revisions?pageSize=20",
                 token, project=project).get("revisions", [])
    revs.sort(key=lambda r: r["createTime"])
    serving = {t.get("revision", "").split("/")[-1]: t.get("percent", 0)
               for t in svc.get("trafficStatuses", [])}

    def env_of(r: dict) -> dict[str, str]:
        return {e["name"]: e.get("value", "<secret>") for e in r["containers"][0].get("env", [])}

    deployments, prev_env, configs = [], {}, {}
    for r in revs:
        name = r["name"].split("/")[-1]
        env = env_of(r)
        image = r["containers"][0]["image"].split("/")[-1]
        diff = [{"file": "cloud-run env", "key": k, "old": prev_env.get(k, ""), "new": env.get(k, "")}
                for k in sorted(set(env) | set(prev_env)) if prev_env.get(k) != env.get(k) and prev_env]
        deployments.append({"id": f"D-{name}", "service": service, "version": env.get("APP_VERSION", "?"),
                            "revision": name, "ts": r["createTime"][:19] + "Z",
                            "traffic_percent": serving.get(name, 0),
                            "summary": f"Cloud Run revision {name} (image {image})",
                            "diff": diff})
        configs[name] = env
        prev_env = env
    (out / "deployments.json").write_text(json.dumps(deployments, indent=1))
    for name, env in configs.items():
        text = "\n".join(f"{k}={v}" for k, v in sorted(env.items())) + "\n"
        (out / "config" / f"{name}.env").write_text(text)

    # ---- alerts: evaluate the same conditions as the Monitoring alert policies, over this window ----
    alerts, aid = [], 0

    def alert(name: str, pts: list[dict], thr: float, sev: str) -> None:
        nonlocal aid
        hot = [p for p in pts if p["value"] > thr]
        if hot:
            aid += 1
            alerts.append({"id": f"A-{aid}", "ts": hot[0]["ts"], "severity": sev, "service": service,
                           "name": name, "status": "firing" if pts[-1]["value"] > thr else "resolved",
                           "condition": f"> {thr} for 1m", "source": "cloud-monitoring policy"})
    alert("HighErrorRate5xx", metrics[1]["points"], 0.05, "critical")
    alert("P95LatencySLOBurn", metrics[2]["points"], 1500, "critical")
    (out / "alerts.json").write_text(json.dumps(alerts, indent=1))

    (out / "runbooks" / "payments-api-rollback.md").write_text(
        "# Runbook: payments-api rollback (Cloud Run)\n1. Confirm the faulty revision via "
        "get_recent_deployments (env diff) and the change ticket.\n2. Propose `rollback traffic to "
        "<previous revision>` with target_revision set; the on-call lead approves; apply_remediation runs "
        "`gcloud run services update-traffic --to-revisions <rev>=100`.\n3. Watch http_5xx_rate and p95 for 5 "
        "minutes.\n4. Open a postmortem.\n")
    (out / "incident.json").write_text(json.dumps({
        "id": inc, "opened_ts": _iso(end), "reporter": "cloud-monitoring",
        "summary": f"{service}: 5xx rate / latency alert firing; customers report failed transfers",
        "severity_guess": "SEV2", "window": {"from": _iso(start), "to": _iso(end)},
        "source": {"type": "gcp", "project": project, "region": region, "service": service}}, indent=1))

    manifest = {str(f.relative_to(out)): hashlib.sha256(f.read_bytes()).hexdigest()
                for f in sorted(p for p in out.rglob("*") if p.is_file() and p.name != "manifest.json")}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return out


def main(argv: list[str]) -> None:
    if not argv or argv[0] != "snapshot":
        print(__doc__)
        sys.exit(2)
    kw = {argv[i].lstrip("-"): argv[i + 1] for i in range(1, len(argv) - 1, 2)}
    out = snapshot(kw["project"], kw.get("service", "payments-api"), kw.get("region", "asia-southeast1"),
                   int(kw.get("minutes", "45")))
    n_logs = sum(1 for _ in (out / "logs.jsonl").open())
    print(f"snapshot: {out}  ({n_logs} log lines, sealed)\nexport SRE_BUNDLE={out}")


if __name__ == "__main__":
    main(sys.argv[1:])
