#!/usr/bin/env bash
# Four MCP servers on Cloud Run: one image, one service account each, least privilege, internal ingress,
# IAM-authenticated. Only remediation-mcp can change anything, and only Cloud Run traffic.
set -euo pipefail
source "$(dirname "$0")/env.sh"
HERE="$(cd "$(dirname "$0")" && pwd)"
TAG="$REGION-docker.pkg.dev/$PROJECT/$REPO/mcp-servers:$(git -C "$HERE" rev-parse --short HEAD 2>/dev/null || date +%s)"
gcloud builds submit "$HERE/../.." --config /dev/stdin --project "$PROJECT" --quiet <<YAML
steps: [{name: gcr.io/cloud-builders/docker, args: [build, -t, "$TAG", -f, mcp_servers/Dockerfile, .]}]
images: ["$TAG"]
YAML
AGENT_SA="sre-agent@$PROJECT.iam.gserviceaccount.com"
gcloud iam service-accounts describe "$AGENT_SA" --project "$PROJECT" >/dev/null 2>&1 || \
  gcloud iam service-accounts create sre-agent --display-name "SRE agent squad (Agent Engine caller)" --project "$PROJECT"
# the agent runtime also reads/writes the shared proposal store (propose, gate, dry-run)
gsutil -q iam ch "serviceAccount:$AGENT_SA:objectAdmin" "gs://$PROJECT-payments-demo" || true
deploy() { # name roles...
  local name="$1"; shift
  local sa="$name@$PROJECT.iam.gserviceaccount.com"
  gcloud iam service-accounts describe "$sa" --project "$PROJECT" >/dev/null 2>&1 || \
    gcloud iam service-accounts create "$name" --display-name "$name" --project "$PROJECT"
  for r in "$@"; do gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$sa" --role "$r" -q >/dev/null; done
  EXTRA=""
  if [ "$name" = "remediation-mcp" ]; then
    EXTRA=",PROPOSAL_STORE=gcs,PROPOSAL_BUCKET=$PROJECT-payments-demo"
    gsutil -q iam ch "serviceAccount:$sa:objectAdmin" "gs://$PROJECT-payments-demo"
  fi
  gcloud run deploy "$name" --image "$TAG" --region "$REGION" --project "$PROJECT" --service-account "$sa" \
    --no-allow-unauthenticated --ingress internal --min-instances 0 --max-instances 2 --cpu 1 --memory 512Mi \
    --set-env-vars "MCP_SERVER=${name%-mcp},SRE_SOURCE=gcp,PROJECT=$PROJECT,REGION=$REGION$EXTRA" --quiet
  gcloud run services add-iam-policy-binding "$name" --region "$REGION" --project "$PROJECT" \
    --member "serviceAccount:$AGENT_SA" --role roles/run.invoker -q >/dev/null
  echo "$name -> $(gcloud run services describe "$name" --region "$REGION" --project "$PROJECT" --format 'value(status.url)')"
}
deploy observability-mcp roles/monitoring.viewer roles/logging.viewer
deploy release-mcp      roles/run.viewer roles/clouddeploy.viewer
deploy incident-mcp     roles/logging.logWriter
deploy remediation-mcp  roles/run.developer roles/logging.logWriter   # only SA with run.services.update
echo "export OBS_MCP_URL=... RELEASE_MCP_URL=... INCIDENT_MCP_URL=... REMEDIATION_MCP_URL=... SRE_TOOLS=mcp"
