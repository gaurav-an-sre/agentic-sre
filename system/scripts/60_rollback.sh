#!/usr/bin/env bash
# Manual rollback (what apply_remediation does for an approved proposal): 100% traffic to a revision.
set -euo pipefail
source "$(dirname "$0")/env.sh"
REV="${1:?revision name, e.g. payments-api-00003-abc}"
gcloud run services update-traffic "$SERVICE" --region "$REGION" --project "$PROJECT" --to-revisions "$REV=100"
