#!/usr/bin/env bash
# Pause (on) or resume (off) ALL agent actuation: writes control/red_button.json in the proposal
# store, checked per-request by remediation-mcp - so it also stops actuation on still-serving old
# revisions (an env-var flip only reaches new instances). Human-only: runs under YOUR gcloud creds,
# and the agent identity cannot write control/*. Usage: 80_red_button.sh on "reason" | off
set -euo pipefail
source "$(dirname "$0")/env.sh"
FLAG="gs://$PROJECT-payments-demo/control/red_button.json"
case "${1:-}" in
  on)  who="$(gcloud config get-value account 2>/dev/null)"
       printf '{"reason":"%s","pressed_by":"%s","ts":"%s"}\n' \
         "${2:-pressed by $who}" "$who" "$(date -u +%FT%TZ)" | gsutil -q cp - "$FLAG"
       echo "red button ON - all agent actuation is paused" ;;
  off) gsutil -q rm "$FLAG" 2>/dev/null || echo "no red-button flag to clear"
       echo "red button OFF - actuation resumed" ;;
  *) echo "usage: $0 on [reason] | off" >&2; exit 2 ;;
esac
