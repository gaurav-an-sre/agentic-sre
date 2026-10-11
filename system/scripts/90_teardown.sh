#!/usr/bin/env bash
# Remove everything billable. Keeps IAM roles.
set -euo pipefail
source "$(dirname "$0")/env.sh"
for svc in "$SERVICE" checkout storefront sre-trigger observability-mcp release-mcp incident-mcp remediation-mcp grafana; do
  gcloud run services delete "$svc" --region "$REGION" --project "$PROJECT" -q || true
done
gcloud sql instances delete "$SQL_INSTANCE" --project "$PROJECT" -q || true
gcloud artifacts repositories delete "$REPO" --location "$REGION" --project "$PROJECT" -q || true
gsutil -m rm -r "gs://$PROJECT-payments-demo" || true
for n in $(gcloud alpha monitoring policies list --project "$PROJECT" --filter 'userLabels.service="payments-api"' --format 'value(name)'); do
  gcloud alpha monitoring policies delete "$n" --project "$PROJECT" -q; done
echo "torn down."
