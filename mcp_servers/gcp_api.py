"""Thin REST adapters for SRE_SOURCE=gcp. Auth = ADC token (the Cloud Run service account)."""

from __future__ import annotations

import json
import subprocess
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

MON = "https://monitoring.googleapis.com/v3"
LOGS = "https://logging.googleapis.com/v2"
RUN = "https://run.googleapis.com/v2"
META = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"


def token() -> str:
    try:
        req = urllib.request.Request(META, headers={"Metadata-Flavor": "Google"})
        with urllib.request.urlopen(req, timeout=2) as r:
            return json.loads(r.read())["access_token"]
    except OSError:
        return subprocess.run(["gcloud", "auth", "print-access-token"], check=True,
                              capture_output=True, text=True).stdout.strip()


def call(url: str, project: str, body: dict | None = None, method: str | None = None) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token()}", "x-goog-user-project": project,
                                          "Content-Type": "application/json"},
                                 method=method or ("POST" if body is not None else "GET"))
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"{}")


def iso(d: datetime) -> str:
    return d.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def series(project: str, mfilter: str, minutes: int, aligner: str, reducer: str = "REDUCE_SUM") -> list[dict]:
    end = datetime.now(UTC)
    start = end - timedelta(minutes=minutes)
    q = (f"filter={urllib.parse.quote(mfilter)}&interval.startTime={iso(start)}&interval.endTime={iso(end)}"
         f"&aggregation.alignmentPeriod=60s&aggregation.perSeriesAligner={aligner}"
         f"&aggregation.crossSeriesReducer={reducer}")
    pts: dict[str, float] = {}
    for ts in call(f"{MON}/projects/{project}/timeSeries?{q}", project).get("timeSeries", []):
        for p in ts["points"]:
            v = p["value"]
            pts[p["interval"]["endTime"]] = pts.get(p["interval"]["endTime"], 0.0) + float(
                v.get("doubleValue", v.get("int64Value", 0)))
    return [{"ts": t, "value": round(v, 3)} for t, v in sorted(pts.items())]


def log_entries(project: str, service: str, minutes: int, severity: str, limit: int) -> list[dict]:
    start = iso(datetime.now(UTC) - timedelta(minutes=minutes))
    f = f'resource.type="cloud_run_revision" AND resource.labels.service_name="{service}" AND timestamp>="{start}"'
    if severity.upper() != "ALL":
        f += f" AND severity>={severity.upper()}"
    body = {"resourceNames": [f"projects/{project}"], "filter": f, "orderBy": "timestamp desc", "pageSize": limit}
    out = []
    for e in reversed(call(f"{LOGS}/entries:list", project, body).get("entries", [])):
        jp = e.get("jsonPayload", {}) or {"message": e.get("textPayload", "")}
        out.append({"id": e["insertId"], "ts": e["timestamp"], "service": service, "level": e.get("severity"),
                    "revision": e["resource"]["labels"].get("revision_name"), "msg": jp.get("message", ""),
                    **{k: v for k, v in jp.items() if k != "message"}})
    return out


def alert_incidents(project: str) -> list[dict]:
    pols = call(f"{MON}/projects/{project}/alertPolicies", project).get("alertPolicies", [])
    return [{"id": p["name"].split("/")[-1], "name": p["displayName"], "enabled": p.get("enabled", True),
             "conditions": [c["displayName"] for c in p.get("conditions", [])]} for p in pols]


def revisions(project: str, region: str, service: str) -> list[dict]:
    svc = call(f"{RUN}/projects/{project}/locations/{region}/services/{service}", project)
    revs = call(f"{RUN}/projects/{project}/locations/{region}/services/{service}/revisions?pageSize=20",
                project).get("revisions", [])
    serving = {t.get("revision", "").split("/")[-1]: t.get("percent", 0) for t in svc.get("trafficStatuses", [])}
    out = []
    for r in sorted(revs, key=lambda r: r["createTime"]):
        name = r["name"].split("/")[-1]
        out.append({"id": name, "revision": name, "created": r["createTime"], "traffic_percent": serving.get(name, 0),
                    "image": r["containers"][0]["image"].split("/")[-1],
                    "env": {e["name"]: e.get("value", "<secret>") for e in r["containers"][0].get("env", [])}})
    return out


def shift_traffic(project: str, region: str, service: str, revision: str, percent: int) -> dict:
    url = f"{RUN}/projects/{project}/locations/{region}/services/{service}?updateMask=traffic"
    body = {"traffic": [{"type": "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION", "revision": revision, "percent": percent}]}
    if percent < 100:
        body["traffic"].append({"type": "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST", "percent": 100 - percent})
    op = call(url, project, body, method="PATCH")
    return {"operation": op.get("name"), "service": service, "revision": revision, "percent": percent}
