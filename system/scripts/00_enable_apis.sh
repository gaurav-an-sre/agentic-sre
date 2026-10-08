#!/usr/bin/env bash
# Enable the APIs the live demo needs. Requires billing linked to the project.
set -euo pipefail
source "$(dirname "$0")/env.sh"
gcloud services enable run.googleapis.com sqladmin.googleapis.com monitoring.googleapis.com \
  logging.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com --project "$PROJECT"
echo "APIs enabled."
