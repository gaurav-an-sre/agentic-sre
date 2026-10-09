#!/usr/bin/env bash
# PagerDuty webhook + human approve endpoint -> agent squad. One small Cloud Run service
# (agents/trigger). Point the PagerDuty webhook at /pagerduty and a Slack slash command at /approve.
set -euo pipefail
source "$(dirname "$0")/env.sh"
HERE="$(cd "$(dirname "$0")" && pwd)"
: "${AGENT_ENGINE_ID:?set AGENT_ENGINE_ID (printed by agents/v2/deploy_agent_engine.py)}"
: "${PAGERDUTY_WEBHOOK_SECRET:?set PAGERDUTY_WEBHOOK_SECRET}"
printf '%s' "$PAGERDUTY_WEBHOOK_SECRET" | gcloud secrets create pagerduty-webhook-secret --data-file=- --project "$PROJECT" 2>/dev/null || \
  printf '%s' "$PAGERDUTY_WEBHOOK_SECRET" | gcloud secrets versions add pagerduty-webhook-secret --data-file=- --project "$PROJECT"

# the token a human sends to POST /approve - never committed, never shown to the model
APPROVE_TOKEN="${APPROVE_TOKEN:-$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)}"
printf '%s' "$APPROVE_TOKEN" | gcloud secrets create approve-token --data-file=- --project "$PROJECT" 2>/dev/null || \
  printf '%s' "$APPROVE_TOKEN" | gcloud secrets versions add approve-token --data-file=- --project "$PROJECT"

SA="sre-agent@$PROJECT.iam.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role roles/aiplatform.user -q >/dev/null
# proposals live in GCS in the cloud deployment: this service writes approvals, so it needs objectAdmin
gsutil iam ch "serviceAccount:$SA:objectAdmin" "gs://$PROJECT-payments-demo" -q
for s in pagerduty-webhook-secret approve-token; do
  gcloud secrets add-iam-policy-binding "$s" --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor --project "$PROJECT" -q >/dev/null
done

cp "$HERE/../../agents/common/proposals.py" "$HERE/../../agents/trigger/proposals.py"
TAG="$REGION-docker.pkg.dev/$PROJECT/$REPO/sre-trigger:$(date +%s)"
gcloud builds submit "$HERE/../../agents/trigger" --tag "$TAG" --project "$PROJECT" --quiet
rm -f "$HERE/../../agents/trigger/proposals.py"
gcloud run deploy sre-trigger --image "$TAG" --region "$REGION" --project "$PROJECT" --service-account "$SA" \
  --allow-unauthenticated --max-instances 1 \
  --set-env-vars "PROJECT=$PROJECT,REGION=$REGION,AGENT_ENGINE_ID=$AGENT_ENGINE_ID,PROPOSAL_STORE=gcs,PROPOSAL_BUCKET=$PROJECT-payments-demo" \
  --set-secrets "PAGERDUTY_WEBHOOK_SECRET=pagerduty-webhook-secret:latest,APPROVE_TOKEN=approve-token:latest" --quiet
URL="$(gcloud run services describe sre-trigger --region "$REGION" --project "$PROJECT" --format 'value(status.url)')"
echo "PagerDuty webhook URL: $URL/pagerduty"
echo "Approve endpoint:      POST $URL/approve  (X-Approve-Token: <approve-token secret>)"
echo "Slack slash command -> POST $URL/approve with body {proposal_id, approver}"
