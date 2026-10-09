#!/usr/bin/env bash
# Public edge service: storefront -> checkout -> payments-api. Deploy after 22_deploy_checkout.sh.
set -euo pipefail
source "$(dirname "$0")/env.sh"
HERE="$(cd "$(dirname "$0")" && pwd)"
CHECKOUT_URL="$(gcloud run services describe checkout --region "$REGION" --project "$PROJECT" --format 'value(status.url)')"
TAG="$REGION-docker.pkg.dev/$PROJECT/$REPO/storefront:$(date +%s)"
gcloud builds submit "$HERE/../storefront" --tag "$TAG" --project "$PROJECT" --quiet
gcloud run deploy storefront --image "$TAG" --region "$REGION" --project "$PROJECT" --allow-unauthenticated \
  --min-instances 1 --max-instances 3 \
  --set-env-vars "CHECKOUT_URL=$CHECKOUT_URL" --labels "app=storefront" --quiet
echo "storefront: $(gcloud run services describe storefront --region "$REGION" --project "$PROJECT" --format 'value(status.url)')"
