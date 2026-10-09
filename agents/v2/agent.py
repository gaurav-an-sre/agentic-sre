"""v2 - multi-agent on ADK with the control plane in code.

  collectors (ParallelAgent, read-only, each writes a short summary to session state)
      -> investigator (timeline + root cause + ONE proposal; propose only)
      -> scribe (postmortem from the investigator's output)

Every tool call passes through agents.common.control_plane.before_tool/after_tool:
audit log, citation validator, approval gate. The apply step is a separate agent that only
exists so the gate has something to deny until a human approves."""

from __future__ import annotations

import os

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent

from agents.common import tools as t
from agents.common.control_plane import after_tool, before_tool
from agents.common.mcp_tools import toolset, use_mcp

MODEL = os.environ.get("SRE_MODEL", "gemini-2.5-flash")
CB = {"before_tool_callback": before_tool, "after_tool_callback": after_tool}


def _collector(name: str, tools: list, what: str) -> LlmAgent:
    return LlmAgent(
        name=name, model=MODEL, tools=tools, output_key=name, **CB,
        instruction=(f"Read-only collector. Gather {what} for the incident. Output <=12 bullet lines; every "
                     "line that states a fact carries the evidence id it came from (L00042 / D-3 / A-1). "
                     "Do not guess root cause."),
    )


if use_mcp():  # production wiring: tools live behind the MCP servers, each with its own IAM identity
    METRICS_T = [toolset("OBS_MCP_URL", ["get_service_health", "query_metrics", "get_slo"])]
    LOGS_T = [toolset("OBS_MCP_URL", ["get_logs", "get_alerts"])]
    CHANGE_T = [toolset("RELEASE_MCP_URL")]
    INVESTIGATOR_T = [toolset("OBS_MCP_URL", ["query_metrics", "get_logs"]), toolset("RELEASE_MCP_URL", ["list_revisions"]),
                      t.propose_remediation]
    SCRIBE_T = [toolset("INCIDENT_MCP_URL", ["write_postmortem", "create_issue"])]
    APPLY_T = [toolset("REMEDIATION_MCP_URL")]
else:
    METRICS_T = [t.verify_bundle, t.get_service_health, t.query_metrics]
    LOGS_T = [t.get_logs, t.get_alerts]
    CHANGE_T = [t.get_recent_deployments, t.read_config, t.read_runbook]
    INVESTIGATOR_T = [t.query_metrics, t.get_logs, t.get_recent_deployments, t.propose_remediation]
    SCRIBE_T = [t.write_postmortem]
    APPLY_T = [t.apply_remediation]

collectors = ParallelAgent(
    name="collectors",
    sub_agents=[
        _collector("metrics_collector", METRICS_T, "which services/metrics moved, when (minute), baseline vs now"),
        _collector("logs_collector", LOGS_T, "the first error lines per service, their timestamps, and the firing alerts"),
        _collector("change_collector", CHANGE_T,
                   "every deployment/config change in the window with its diff, and the matching runbook"),
    ],
)

investigator = LlmAgent(
    name="investigator", model=MODEL, output_key="investigation", **CB,
    tools=INVESTIGATOR_T,
    instruction=(
        "You are the incident investigator. Inputs from collectors:\n"
        "METRICS:\n{metrics_collector}\nLOGS:\n{logs_collector}\nCHANGES:\n{change_collector}\n\n"
        "Build a minute-by-minute timeline. Rule out at least one alternative explanation explicitly. "
        "Decide the single most likely root cause. Then call propose_remediation exactly once with the "
        "evidence ids that support it and the exact revision to roll back to if that is the action. "
        "You cannot apply anything; a human approves. End with: root cause, confidence, proposal id."
    ),
)

scribe = LlmAgent(
    name="scribe", model=MODEL, tools=SCRIBE_T, output_key="postmortem", **CB,
    instruction=("Write a blameless postmortem (markdown: summary, impact, timeline, root cause, what went "
                 "well, what went badly, 3 action items with owners) from:\n{investigation}\n"
                 "Then call write_postmortem with it."),
)

applier = LlmAgent(
    name="applier", model=MODEL, tools=APPLY_T, **CB,
    instruction="Apply the proposal id you are given (apply_remediation, or shift_traffic with its service, "
                "target revision and the open incident_id). With shift_traffic call dry_run=true first and show "
                "the plan; never pass override_hold yourself - only a human may. Report results verbatim.",
)

root_agent = SequentialAgent(name="sre_v2", sub_agents=[collectors, investigator, scribe])
