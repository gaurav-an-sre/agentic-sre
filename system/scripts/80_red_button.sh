#!/usr/bin/env bash
# Pause (on) or resume (off) ALL agent actuation: flips AGENT_ACTUATION_PAUSED on remediation-mcp.
# Human-only, no model involved. Usage: 80_red_button.sh on "reason" | off
set -euo pipefail
source "$(dirname "$0")/env.sh"
case "${1:-}" in
  on)  gcloud run services update remediation-mcp --region "$REGION" --project "$PROJECT" \
         --update-env-vars "AGENT_ACTUATION_PAUSED=1,RED_BUTTON_REASON=${2:-pressed by $(gcloud config get-value account 2>/dev/null)}" --quiet ;;
  off) gcloud run services update remediation-mcp --region "$REGION" --project "$PROJECT" \
         --remove-env-vars AGENT_ACTUATION_PAUSED,RED_BUTTON_REASON --quiet ;;
  *) echo "usage: $0 on [reason] | off" >&2; exit 2 ;;
esac
gcloud run services describe remediation-mcp --region "$REGION" --project "$PROJECT" \
  --format 'value(spec.template.spec.containers[0].env)' | tr ';' '\n' | grep -i actuation || echo "actuation resumed"
