#!/usr/bin/env bash
# Closed-loop transfer traffic from your laptop (no extra cloud resources). Ctrl-C to stop.
set -euo pipefail
source "$(dirname "$0")/env.sh"
HERE="$(cd "$(dirname "$0")" && pwd)"
URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format 'value(status.url)')"
BASE_URL="$URL" CONCURRENCY="${CONCURRENCY:-40}" DURATION_S="${DURATION_S:-1200}" \
  uv run --with httpx python "$HERE/../loadgen/loadgen.py"
