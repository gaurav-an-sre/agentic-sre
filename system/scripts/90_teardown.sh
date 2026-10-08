#!/usr/bin/env bash
# Remove everything billable. Keeps IAM roles.
set -euo pipefail
source "$(dirname "$0")/env.sh"
gcloud run services delete "$SERVICE" --region "$REGION" --project "$PROJECT" -q || true
gcloud sql instances delete "$SQL_INSTANCE" --project "$PROJECT" -q || true
gcloud artifacts repositories delete "$REPO" --location "$REGION" --project "$PROJECT" -q || true
gsutil -m rm -r "gs://$PROJECT-payments-demo" || true
for n in $(gcloud alpha monitoring policies list --project "$PROJECT" --filter 'userLabels.service="payments-api"' --format 'value(name)'); do
  gcloud alpha monitoring policies delete "$n" --project "$PROJECT" -q; done
echo "torn down."
