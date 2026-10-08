"""MCP tool servers - the only way agents touch anything.

Four small services, one per concern, each deployed as its own Cloud Run service with its own service
account (system/scripts/70_mcp_servers.sh):

  observability-mcp  read-only   Cloud Monitoring / Managed Prometheus, Cloud Logging, alerts, SLOs
  release-mcp        read-only   Cloud Run revisions, env diffs, runtime config, runbooks
  incident-mcp       Jira/Confluence writes only (never production)
  remediation-mcp    the ONE production write path: shift_traffic, gated on an approval record

SRE_SOURCE=bundle (default) serves the frozen evidence bundle so everything runs offline and in CI;
SRE_SOURCE=gcp serves the live project (PROJECT/REGION env) through the Google Cloud REST APIs.
"""
