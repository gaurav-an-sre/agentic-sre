#!/usr/bin/env bash
# One-off: Cloud SQL (smallest Postgres), schema, runtime SA, artifact repo. ~10 min, mostly Cloud SQL.
set -euo pipefail
source "$(dirname "$0")/env.sh"
HERE="$(cd "$(dirname "$0")" && pwd)"

gcloud artifacts repositories describe "$REPO" --location "$REGION" --project "$PROJECT" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "$REPO" --repository-format docker --location "$REGION" --project "$PROJECT"

if ! gcloud sql instances describe "$SQL_INSTANCE" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud sql instances create "$SQL_INSTANCE" --database-version POSTGRES_16 --edition ENTERPRISE \
    --tier db-f1-micro --region "$REGION" --storage-size 10 --storage-type HDD \
    --no-storage-auto-increase --project "$PROJECT"
fi
DB_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)"
gcloud sql users create "$DB_USER" --instance "$SQL_INSTANCE" --password "$DB_PASSWORD" --project "$PROJECT" 2>/dev/null || \
  gcloud sql users set-password "$DB_USER" --instance "$SQL_INSTANCE" --password "$DB_PASSWORD" --project "$PROJECT"
gcloud sql databases describe "$DB_NAME" --instance "$SQL_INSTANCE" --project "$PROJECT" >/dev/null 2>&1 || \
  gcloud sql databases create "$DB_NAME" --instance "$SQL_INSTANCE" --project "$PROJECT"

# password lives in Secret Manager, never in a revision's env
if gcloud secrets describe payments-db-password --project "$PROJECT" >/dev/null 2>&1; then
  printf '%s' "$DB_PASSWORD" | gcloud secrets versions add payments-db-password --data-file=- --project "$PROJECT"
else
  printf '%s' "$DB_PASSWORD" | gcloud secrets create payments-db-password --data-file=- --project "$PROJECT"
fi

gcloud iam service-accounts describe "$RUNTIME_SA" --project "$PROJECT" >/dev/null 2>&1 || \
  gcloud iam service-accounts create payments-api-runtime --display-name "payments-api runtime" --project "$PROJECT"
for r in roles/cloudsql.client roles/logging.logWriter roles/monitoring.metricWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$RUNTIME_SA" --role "$r" -q >/dev/null
done
gcloud secrets add-iam-policy-binding payments-db-password --member "serviceAccount:$RUNTIME_SA" \
  --role roles/secretmanager.secretAccessor --project "$PROJECT" -q >/dev/null

# schema: load through a short-lived Cloud SQL import from GCS
BUCKET="gs://$PROJECT-payments-demo"
gsutil ls -b "$BUCKET" >/dev/null 2>&1 || gsutil mb -l "$REGION" -p "$PROJECT" "$BUCKET"
gsutil cp "$HERE/../payments_api/schema.sql" "$BUCKET/schema.sql"
SQL_SA="$(gcloud sql instances describe "$SQL_INSTANCE" --project "$PROJECT" --format 'value(serviceAccountEmailAddress)')"
gsutil iam ch "serviceAccount:$SQL_SA:objectViewer" "$BUCKET"
gcloud sql import sql "$SQL_INSTANCE" "$BUCKET/schema.sql" --database "$DB_NAME" --user "$DB_USER" --project "$PROJECT" -q
echo "provisioned: $CONN_NAME, db=$DB_NAME, user=$DB_USER (password in Secret Manager: payments-db-password)"
