#!/usr/bin/env bash
# Turn sre/slo.yaml into burn-rate alert policies on Cloud Monitoring.
# Keeps the *meaning* of the SLO in config so an SLO review is a YAML diff, not a gcloud archeology dig.
set -euo pipefail
source "$(dirname "$0")/env.sh"
HERE="$(cd "$(dirname "$0")" && pwd)"

python3 -c "import yaml" 2>/dev/null || { echo "pyyaml needed for sre/slo.yaml"; exit 1; }
mkdir -p /tmp/slo_policies && rm -f /tmp/slo_policies/*.json

python3 - "$HERE/../../sre/slo.yaml" /tmp/slo_policies <<'PY'
import json, sys, yaml
doc = yaml.safe_load(open(sys.argv[1]))
out = sys.argv[2]
for svc, cfg in doc["services"].items():
    for slo in cfg["slos"]:
        if "indicator" not in slo:
            continue
        for name, br in doc["burn_rates"].items():
            threshold = br["factor"] * (1 - slo["target"])
            f = ('resource.type="cloud_run_revision" AND resource.label.service_name="%s" AND '
                 'metric.type="run.googleapis.com/request_count" AND metric.label.response_code_class="5xx"') % svc
            p = {"displayName": f"SLO burn {svc}/{slo['name']} {name}({br['window_minutes']}m)",
                 "combiner": "OR",
                 "conditions": [{"displayName": f"{slo['name']} burn > {br['factor']}x",
                                 "conditionThreshold": {"filter": f, "comparison": "COMPARISON_GT",
                                                        "thresholdValue": round(threshold, 6),
                                                        "duration": f"{br['window_minutes']}s",
                                                        "aggregations": [{"alignmentPeriod": "60s",
                                                                          "perSeriesAligner": "ALIGN_RATE",
                                                                          "crossSeriesReducer": "REDUCE_SUM",
                                                                          "groupByFields": ["resource.label.service_name"]}]}}],
                 "userLabels": {"service": svc, "slo": slo["name"], "burn": name}}
            json.dump(p, open(f"{out}/{svc}-{slo['name']}-{name}.json", "w"))
PY

for f in /tmp/slo_policies/*.json; do
  name=$(python3 -c "import json,sys; print(json.load(open('$f'))['displayName'])")
  gcloud monitoring policies list --project "$PROJECT" --filter "displayName=\"$name\"" --format 'value(name)' | grep -q . && continue
  gcloud monitoring policies create --policy-from-file "$f" --project "$PROJECT"
done
echo "SLO burn-rate policies in place (definitions live in sre/slo.yaml)"
