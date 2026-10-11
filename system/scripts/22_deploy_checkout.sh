#!/usr/bin/env bash
# Storefront + checkout on Cloud Run (public), calling payments-api. usage: 22_deploy_checkout.sh [baseline|promo]
set -euo pipefail
source "$(dirname "$0")/env.sh"
HERE="$(cd "$(dirname "$0")" && pwd)"
PRICING="${1:-baseline}"
PAY_URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format 'value(status.url)')"
TAG="$REGION-docker.pkg.dev/$PROJECT/$REPO/checkout:$(date +%s)"
gcloud builds submit "$HERE/../checkout" --tag "$TAG" --project "$PROJECT" --quiet
gcloud run deploy checkout --image "$TAG" --region "$REGION" --project "$PROJECT" --allow-unauthenticated \
  --min-instances 1 --max-instances 3 --cpu 1 --memory 512Mi \
  --set-env-vars "PAYMENTS_URL=$PAY_URL,PRICING_PROFILE=$PRICING" --labels "app=checkout,pricing=$PRICING" --quiet
gcloud run services describe checkout --region "$REGION" --project "$PROJECT" --format 'value(status.url)'
