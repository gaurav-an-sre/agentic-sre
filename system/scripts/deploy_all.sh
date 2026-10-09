#!/usr/bin/env bash
# Deploy the whole demo end to end. usage: PROJECT=my-project ./deploy_all.sh
# Order matters: platform -> services -> traffic -> agents -> human bridge.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
"$HERE/00_enable_apis.sh"
"$HERE/10_provision.sh"          # ~10 min, mostly Cloud SQL
"$HERE/20_deploy.sh" v2.14.2 50 5000   # payments-api healthy baseline
"$HERE/22_deploy_checkout.sh" baseline
"$HERE/23_deploy_storefront.sh"
"$HERE/30_alerts.sh"
"$HERE/32_grafana.sh"
"$HERE/34_pagerduty.sh"
"$HERE/35_dashboard.sh"
echo "system up. Next (optional): ./50_loadgen.sh traffic, ./40_break.sh to break it,"
echo "agents/v2/deploy_agent_engine.py, ./70_mcp_servers.sh, ./75_trigger.sh"
