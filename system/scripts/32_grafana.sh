#!/usr/bin/env bash
# Grafana on Cloud Run, reading Cloud Monitoring (incl. Managed Prometheus) with its own read-only SA.
set -euo pipefail
source "$(dirname "$0")/env.sh"
HERE="$(cd "$(dirname "$0")" && pwd)"
SA="grafana@$PROJECT.iam.gserviceaccount.com"
gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1 || \
  gcloud iam service-accounts create grafana --display-name "Grafana (read-only)" --project "$PROJECT"
for r in roles/monitoring.viewer roles/logging.viewer; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role "$r" -q >/dev/null; done
if ! gcloud secrets describe grafana-admin-password --project "$PROJECT" >/dev/null 2>&1; then
  openssl rand -base64 18 | tr -d '/+=' | gcloud secrets create grafana-admin-password --data-file=- --project "$PROJECT"; fi
gcloud secrets add-iam-policy-binding grafana-admin-password --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor --project "$PROJECT" -q >/dev/null
TAG="$REGION-docker.pkg.dev/$PROJECT/$REPO/grafana:11.4.0"
gcloud builds submit "$HERE/../grafana" --tag "$TAG" --project "$PROJECT" --quiet
gcloud run deploy grafana --image "$TAG" --region "$REGION" --project "$PROJECT" --service-account "$SA" \
  --allow-unauthenticated --min-instances 1 --max-instances 1 --cpu 1 --memory 1Gi --port 8080 \
  --set-env-vars "PROJECT=$PROJECT,GF_INSTALL_PLUGINS=googlecloud-logging-datasource" \
  --set-secrets "GF_SECURITY_ADMIN_PASSWORD=grafana-admin-password:latest" --quiet
echo "grafana: $(gcloud run services describe grafana --region "$REGION" --project "$PROJECT" --format 'value(status.url)')  (admin / secret grafana-admin-password)"
