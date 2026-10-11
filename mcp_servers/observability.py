"""observability-mcp (read-only). SA roles: monitoring.viewer, logging.viewer."""

from __future__ import annotations

from statistics import mean

from mcp.server.mcpserver import MCPServer

from agents.common import tools as bundle_tools
from mcp_servers import gcp_api
from mcp_servers.common import PROJECT, gcp_mode, serve

server = MCPServer("observability-mcp", instructions="Read-only metrics, alerts, logs, SLOs. Every record has an id - cite it.")

_METRIC_FILTERS = {
    "http_rps": ('metric.type="run.googleapis.com/request_count"', "ALIGN_RATE", "REDUCE_SUM"),
    "http_5xx_rps": ('metric.type="run.googleapis.com/request_count" AND metric.labels.response_code_class="5xx"',
                     "ALIGN_RATE", "REDUCE_SUM"),
    "http_p95_latency_ms": ('metric.type="run.googleapis.com/request_latencies"', "ALIGN_PERCENTILE_95", "REDUCE_MAX"),
    "instances": ('metric.type="run.googleapis.com/container/instance_count"', "ALIGN_MAX", "REDUCE_SUM"),
}


@server.tool()
def query_metrics(service: str, metric: str, minutes: int = 45) -> dict:
    """1-minute time series for one metric of one Cloud Run service (http_rps, http_5xx_rps/http_5xx_rate,
    http_p95_latency_ms, instances)."""
    if not gcp_mode():
        return bundle_tools.query_metrics(service, metric)
    if metric not in _METRIC_FILTERS:
        return {"error": "unknown metric", "available": sorted(_METRIC_FILTERS)}
    f, aligner, reducer = _METRIC_FILTERS[metric]
    base = f'resource.type="cloud_run_revision" AND resource.labels.service_name="{service}" AND {f}'
    return {"service": service, "metric": metric, "points": gcp_api.series(PROJECT, base, minutes, aligner, reducer)}


@server.tool()
def get_service_health(service: str = "") -> dict:
    """Baseline-vs-now summary per metric plus firing alerts."""
    if not gcp_mode():
        return bundle_tools.get_service_health()
    out = {}
    for m in _METRIC_FILTERS:
        pts = query_metrics(service, m)["points"]
        if pts:
            out[m] = {"baseline": round(mean(p["value"] for p in pts[:10]), 3),
                      "now": round(mean(p["value"] for p in pts[-5:]), 3)}
    return {"services": {service: out}, "alert_policies": gcp_api.alert_incidents(PROJECT)}


@server.tool()
def get_alerts() -> list[dict]:
    """Alerts in the incident window (bundle) or the project's alert policies (gcp)."""
    return gcp_api.alert_incidents(PROJECT) if gcp_mode() else bundle_tools.get_alerts()


@server.tool()
def get_logs(service: str, level: str = "ERROR", lines: int = 30, minutes: int = 45) -> dict:
    """Last N log lines for a service. Each line has an id (bundle: L00042, gcp: Cloud Logging insertId) - cite it."""
    if not gcp_mode():
        return bundle_tools.get_logs(service, level, lines)
    rows = gcp_api.log_entries(PROJECT, service, minutes, level, lines)
    return {"count": len(rows), "lines": rows}


@server.tool()
def get_slo(service: str) -> dict:
    """Pilot SLOs and current burn from the 5xx series (99.9% checkout success; 99.5% payments-api)."""
    target = {"checkout": 0.999, "payments-api": 0.995}.get(service, 0.999)
    s = query_metrics(service, "http_5xx_rate" if not gcp_mode() else "http_5xx_rps")
    pts = s.get("points", [])
    if not pts:
        return {"service": service, "slo_target": target, "error": "no data"}
    now = mean(p["value"] for p in pts[-5:])
    return {"service": service, "slo_target": target, "error_signal_last_5m": round(now, 4),
            "burning": now > (1 - target), "series": s.get("metric")}


if __name__ == "__main__":
    serve(server)
