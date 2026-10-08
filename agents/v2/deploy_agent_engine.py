"""Deploy the v2 squad to Vertex AI Agent Engine (then register it in Gemini Enterprise as a tool/agent).
Nothing here runs unless you call it:  PROJECT=<id> python -m agents.v2.deploy_agent_engine
Requires: pip install -e ".[gcp]"; a staging bucket; the evidence bundle is shipped as extra_packages so the
read tools work identically in the cloud. Live GCP tools are selected per bundle (incident.json "source")."""

from __future__ import annotations

import os

import vertexai
from vertexai import agent_engines

from agents.v2.agent import root_agent

PROJECT = os.environ["PROJECT"]
REGION = os.environ.get("REGION", "asia-southeast1")
BUCKET = os.environ.get("STAGING_BUCKET", f"gs://{PROJECT}-agent-staging")

vertexai.init(project=PROJECT, location=REGION, staging_bucket=BUCKET)
app = agent_engines.AdkApp(agent=root_agent, enable_tracing=True)
remote = agent_engines.create(
    app,
    display_name="sre-v2-thai-retail",
    requirements=["google-adk>=2.9,<3", "google-cloud-aiplatform[agent_engines]"],
    extra_packages=["agents", "evidence/INC-2026-1009"],
    env_vars={"SRE_MODEL": os.environ.get("SRE_MODEL", "gemini-2.5-flash")},
)
print("deployed:", remote.resource_name)
