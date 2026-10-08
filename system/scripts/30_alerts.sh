#!/usr/bin/env bash
# Cloud Monitoring alert policies on the built-in Cloud Run metrics (5xx ratio + p95 latency).
set -euo pipefail
source "$(dirname "$0")/env.sh"
mk() {  # name, display, filter, threshold, aligner
  gcloud monitoring policies list --project "$PROJECT" --filter "displayName=\"$2\"" --format 'value(name)' | grep -q . && return 0
  cat > /tmp/policy.json <<JSON
{"displayName":"$2","combiner":"OR","conditions":[{"displayName":"$2",
 "conditionThreshold":{"filter":"$3","comparison":"COMPARISON_GT","thresholdValue":$4,"duration":"120s",
 "aggregations":[{"alignmentPeriod":"60s","perSeriesAligner":"$5","crossSeriesReducer":"REDUCE_SUM","groupByFields":["resource.label.service_name"]}]}}],
 "userLabels":{"service":"$SERVICE"}}
JSON
  gcloud monitoring policies create --policy-from-file /tmp/policy.json --project "$PROJECT"
}
F5XX="resource.type=\\\"cloud_run_revision\\\" AND resource.label.service_name=\\\"$SERVICE\\\" AND metric.type=\\\"run.googleapis.com/request_count\\\" AND metric.label.response_code_class=\\\"5xx\\\""
FLAT="resource.type=\\\"cloud_run_revision\\\" AND resource.label.service_name=\\\"$SERVICE\\\" AND metric.type=\\\"run.googleapis.com/request_latencies\\\""
mk 5xx "payments-api HighErrorRate5xx" "$F5XX" 20 ALIGN_RATE
mk lat "payments-api P95LatencySLOBurn" "$FLAT" 1500 ALIGN_PERCENTILE_95
echo "alert policies in place: https://console.cloud.google.com/monitoring/alerting?project=$PROJECT"
