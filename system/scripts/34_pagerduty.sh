#!/usr/bin/env bash
# PagerDuty as the paging channel for the alert policies. usage: PAGERDUTY_KEY=<Events v2 integration key> 34_pagerduty.sh
set -euo pipefail
source "$(dirname "$0")/env.sh"
: "${PAGERDUTY_KEY:?set PAGERDUTY_KEY (PagerDuty service -> Integrations -> Google Cloud Monitoring / Events API v2)}"
CH="$(gcloud monitoring channels list --project "$PROJECT" --filter 'displayName="PagerDuty SRE on-call"' --format 'value(name)')"
if [[ -z "$CH" ]]; then
  CH="$(gcloud monitoring channels create --display-name "PagerDuty SRE on-call" --type pagerduty \
        --channel-labels "service_key=$PAGERDUTY_KEY" --project "$PROJECT" --format 'value(name)')"; fi
# every policy we manage pages on-call: payments-api/checkout 5xx+latency AND the SLO burn policies
for p in $(gcloud monitoring policies list --project "$PROJECT" --filter 'userLabels.service:*' --format 'value(name)'); do
  gcloud monitoring policies update "$p" --add-notification-channels "$CH" --project "$PROJECT" -q >/dev/null; done
echo "alert policies page PagerDuty via $CH"
