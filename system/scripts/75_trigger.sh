#!/usr/bin/env bash
# PagerDuty webhook -> agent squad. Small Cloud Run service (agents/trigger) that verifies the PagerDuty
# signature and starts the v2 investigation on Agent Engine. Point the PagerDuty webhook at its URL.
set -euo pipefail
source "$(dirname "$0")/env.sh"
HERE="$(cd "$(dirname "$0")" && pwd)"
: "${AGENT_ENGINE_ID:?set AGENT_ENGINE_ID (printed by agents/v2/deploy_agent_engine.py)}"
: "${PAGERDUTY_WEBHOOK_SECRET:?set PAGERDUTY_WEBHOOK_SECRET}"
printf '%s' "$PAGERDUTY_WEBHOOK_SECRET" | gcloud secrets create pagerduty-webhook-secret --data-file=- --project "$PROJECT" 2>/dev/null || \
  printf '%s' "$PAGERDUTY_WEBHOOK_SECRET" | gcloud secrets versions add pagerduty-webhook-secret --data-file=- --project "$PROJECT"
SA="sre-agent@$PROJECT.iam.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role roles/aiplatform.user -q >/dev/null
gcloud secrets add-iam-policy-binding pagerduty-webhook-secret --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor --project "$PROJECT" -q >/dev/null
TAG="$REGION-docker.pkg.dev/$PROJECT/$REPO/sre-trigger:$(date +%s)"
gcloud builds submit "$HERE/../../agents/trigger" --tag "$TAG" --project "$PROJECT" --quiet
gcloud run deploy sre-trigger --image "$TAG" --region "$REGION" --project "$PROJECT" --service-account "$SA" \
  --allow-unauthenticated --max-instances 1 --set-env-vars "PROJECT=$PROJECT,REGION=$REGION,AGENT_ENGINE_ID=$AGENT_ENGINE_ID" \
  --set-secrets "PAGERDUTY_WEBHOOK_SECRET=pagerduty-webhook-secret:latest" --quiet
echo "PagerDuty webhook URL: $(gcloud run services describe sre-trigger --region "$REGION" --project "$PROJECT" --format 'value(status.url)')/pagerduty"
