#!/usr/bin/env bash
# One Cloud Monitoring dashboard: 5xx ratio, p95, request rate by revision, Cloud SQL connections.
set -euo pipefail
source "$(dirname "$0")/env.sh"
F='resource.type=\"cloud_run_revision\" resource.label.\"service_name\"=\"'"$SERVICE"'\"'
tile() { # title, filter-extra, aligner, reducer, groupBy
  cat <<JSON
{"title":"$1","xyChart":{"dataSets":[{"timeSeriesQuery":{"timeSeriesFilter":{"filter":"$F $2",
 "aggregation":{"alignmentPeriod":"60s","perSeriesAligner":"$3","crossSeriesReducer":"$4","groupByFields":[$5]}}},"plotType":"LINE"}]}}
JSON
}
cat > /tmp/dash.json <<JSON
{"displayName":"payments-api - live SRE demo","mosaicLayout":{"columns":12,"tiles":[
 {"xPos":0,"yPos":0,"width":6,"height":4,"widget":$(tile "5xx requests/s" 'metric.type=\"run.googleapis.com/request_count\" metric.label.\"response_code_class\"=\"5xx\"' ALIGN_RATE REDUCE_SUM '')},
 {"xPos":6,"yPos":0,"width":6,"height":4,"widget":$(tile "p95 latency (ms)" 'metric.type=\"run.googleapis.com/request_latencies\"' ALIGN_PERCENTILE_95 REDUCE_MAX '')},
 {"xPos":0,"yPos":4,"width":6,"height":4,"widget":$(tile "requests/s by revision" 'metric.type=\"run.googleapis.com/request_count\"' ALIGN_RATE REDUCE_SUM '"resource.label.\"revision_name\""')},
 {"xPos":6,"yPos":4,"width":6,"height":4,"widget":{"title":"Cloud SQL connections","xyChart":{"dataSets":[{"timeSeriesQuery":{"timeSeriesFilter":{"filter":"resource.type=\"cloudsql_database\" metric.type=\"cloudsql.googleapis.com/database/postgresql/num_backends\"","aggregation":{"alignmentPeriod":"60s","perSeriesAligner":"ALIGN_MEAN","crossSeriesReducer":"REDUCE_SUM"}}},"plotType":"LINE"}]}}}
]}}
JSON
gcloud monitoring dashboards list --project "$PROJECT" --filter 'displayName="payments-api - live SRE demo"' --format 'value(name)' | grep -q . || \
  gcloud monitoring dashboards create --config-from-file /tmp/dash.json --project "$PROJECT"
echo "dashboard: https://console.cloud.google.com/monitoring/dashboards?project=$PROJECT"
