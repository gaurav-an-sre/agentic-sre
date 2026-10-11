#!/usr/bin/env bash
# Turn sre/slo.yaml into burn-rate alert policies on Cloud Monitoring.
# Every alert is a RATIO (bad / total via denominatorFilter) - never error volume:
# a count-based threshold pages on healthy high traffic and sleeps through low-volume outages.
# Keeps the *meaning* of the SLO in config so an SLO review is a YAML diff, not a gcloud archeology dig.
set -euo pipefail
source "$(dirname "$0")/env.sh"
HERE="$(cd "$(dirname "$0")" && pwd)"

python3 -c "import yaml" 2>/dev/null || { echo "pyyaml needed for sre/slo.yaml"; exit 1; }
mkdir -p /tmp/slo_policies && rm -f /tmp/slo_policies/*


python3 - "$HERE/../../sre/slo.yaml" /tmp/slo_policies <<'PY'
import json, sys, yaml
doc = yaml.safe_load(open(sys.argv[1]))
out = sys.argv[2]
RUN = 'resource.type="cloud_run_revision" AND resource.label.service_name="%s"'
ALIGN = [{"alignmentPeriod": "60s", "perSeriesAligner": "ALIGN_DELTA",
          "crossSeriesReducer": "REDUCE_SUM", "groupByFields": ["resource.label.service_name"]}]

for svc, cfg in doc["services"].items():
    for slo in cfg["slos"]:
        ind = slo.get("indicator")
        if not ind:
            continue
        if ind.get("type") == "log_ratio":
            num = f'resource.type="cloud_run_revision" AND metric.type="logging.googleapis.com/user/{ind["bad_log_metric"]}"'
            den = f'resource.type="cloud_run_revision" AND metric.type="logging.googleapis.com/user/{ind["total_log_metric"]}"'
        else:
            num = (RUN % svc) + ' AND metric.type="run.googleapis.com/request_count" AND metric.label.response_code_class="5xx"'
            den = (RUN % svc) + ' AND metric.type="run.googleapis.com/request_count"'
        for name, br in doc["burn_rates"].items():
            threshold = round(br["factor"] * (1 - slo["target"]), 6)
            p = {"displayName": f"SLO burn {svc}/{slo['name']} {name}({br['window_minutes']}m)",
                 "combiner": "OR",
                 "conditions": [{"displayName": f"{slo['name']} burn > {br['factor']}x of budget",
                                 "conditionThreshold": {
                                     "filter": num, "denominatorFilter": den,
                                     "aggregations": ALIGN, "denominatorAggregations": ALIGN,
                                     "comparison": "COMPARISON_GT", "thresholdValue": threshold,
                                     "duration": f"{br['window_minutes']*60}s"}}],
                 "userLabels": {"service": svc, "slo": slo["name"], "burn": name}}
            json.dump(p, open(f"{out}/{svc}-{slo['name']}-{name}.json", "w"))
            # emit the log-metric spec for the shell to provision first
            if ind.get("type") == "log_ratio":
                json.dump({"total": ind["total_log_metric"], "bad": ind["bad_log_metric"],
                           "filter": ind["log_filter"], "bad_extra": ind["bad_filter"]},
                          open(f"{out}/{svc}-{slo['name']}-metrics.json", "w"))
PY

# provision log-based metrics before policies that read them
for f in /tmp/slo_policies/*-metrics.json; do
  [ -e "$f" ] || continue
  python3 - "$f" <<'PY'
import json, subprocess, sys
m = json.load(open(sys.argv[1]))
for name, filt in ((m["total"], m["filter"]), (m["bad"], m["filter"] + m["bad_extra"])):
    r = subprocess.run(["gcloud", "logging", "metrics", "describe", name,
                        "--project", __import__("os").environ["PROJECT"]], capture_output=True)
    if r.returncode != 0:
        subprocess.run(["gcloud", "logging", "metrics", "create", name,
                        "--project", __import__("os").environ["PROJECT"],
                        "--description", "order_decision SLO metric", "--log-filter", filt], check=True)
        print(f"created log metric {name}")
PY
done

for f in /tmp/slo_policies/*-*.json; do
  case "$f" in *-metrics.json) continue;; esac
  name=$(python3 -c "import json; print(json.load(open('$f'))['displayName'])")
  existing=$(gcloud monitoring policies list --project "$PROJECT" --filter "displayName=\"$name\"" --format 'value(name)' | head -1)
  if [ -n "$existing" ]; then
    # in-place update: same display name but new condition shape (e.g. volume-era policies)
    # must be replaced, not skipped - skip leaves stale thresholds armed
    python3 - "$f" "$existing" <<'PY' > /tmp/policy_update.json
import json, sys
p = json.load(open(sys.argv[1]))
p["name"] = sys.argv[2]          # full resource name of the existing policy
json.dump(p, sys.stdout)
PY
    gcloud alpha monitoring policies update "$existing" --policy-from-file /tmp/policy_update.json --project "$PROJECT"
  else
    gcloud monitoring policies create --policy-from-file "$f" --project "$PROJECT"
  fi
done
echo "SLO burn-rate policies in place (definitions live in sre/slo.yaml)"
