#!/usr/bin/env bash
# Deploy a payments-api revision.  usage: 20_deploy.sh <version> <db_pool_size> [db_pool_timeout_ms]
#   good:  20_deploy.sh v2.14.2 50 5000
#   bad:   20_deploy.sh v2.14.3 5 1500     (the incident - see 40_break.sh)
set -euo pipefail
source "$(dirname "$0")/env.sh"
HERE="$(cd "$(dirname "$0")" && pwd)"
VERSION="${1:?version}"; POOL="${2:?db_pool_size}"; TIMEOUT="${3:-5000}"
TAG="$IMAGE:$VERSION"
BUILD_ID="$(gcloud builds submit "$HERE/../payments_api" --tag "$TAG" --project "$PROJECT" --quiet --async --format 'value(id)')"
until STATUS="$(gcloud builds describe "$BUILD_ID" --project "$PROJECT" --format 'value(status)')" \
      && [[ "$STATUS" != "QUEUED" && "$STATUS" != "WORKING" ]]; do sleep 5; done
[[ "$STATUS" == "SUCCESS" ]] || { echo "build $BUILD_ID: $STATUS" >&2; exit 1; }
gcloud run deploy "$SERVICE" --image "$TAG" --region "$REGION" --project "$PROJECT" \
  --service-account "$RUNTIME_SA" --add-cloudsql-instances "$CONN_NAME" \
  --allow-unauthenticated --min-instances 1 --max-instances 2 --concurrency 80 --cpu 1 --memory 512Mi \
  --set-env-vars "APP_VERSION=$VERSION,DB_POOL_SIZE=$POOL,DB_POOL_TIMEOUT_MS=$TIMEOUT,DB_HOST=/cloudsql/$CONN_NAME,DB_NAME=$DB_NAME,DB_USER=$DB_USER" \
  --set-secrets "DB_PASSWORD=payments-db-password:latest" \
  --labels "app=payments-api,version=${VERSION//./-}" --quiet
URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format 'value(status.url)')"
echo "deployed $VERSION (DB_POOL_SIZE=$POOL) -> $URL"
curl -fsS "$URL/health"; echo
