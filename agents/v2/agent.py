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

MODEL = os.environ.get("SRE_MODEL", "gemini-2.5-flash")
CB = {"before_tool_callback": before_tool, "after_tool_callback": after_tool}


def _collector(name: str, tools: list, what: str) -> LlmAgent:
    return LlmAgent(
        name=name, model=MODEL, tools=tools, output_key=name, **CB,
        instruction=(f"Read-only collector. Gather {what} for the incident. Output <=12 bullet lines; every "
                     "line that states a fact carries the evidence id it came from (L00042 / D-3 / A-1). "
                     "Do not guess root cause."),
    )


collectors = ParallelAgent(
    name="collectors",
    sub_agents=[
        _collector("metrics_collector", [t.verify_bundle, t.get_service_health, t.query_metrics],
                   "which services/metrics moved, when (minute), baseline vs now"),
        _collector("logs_collector", [t.get_logs, t.get_alerts],
                   "the first error lines per service, their timestamps, and the firing alerts"),
        _collector("change_collector", [t.get_recent_deployments, t.read_config, t.read_runbook],
                   "every deployment/config change in the window with its diff, and the matching runbook"),
    ],
)

investigator = LlmAgent(
    name="investigator", model=MODEL, output_key="investigation", **CB,
    tools=[t.query_metrics, t.get_logs, t.get_recent_deployments, t.propose_remediation],
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
    name="scribe", model=MODEL, tools=[t.write_postmortem], output_key="postmortem", **CB,
    instruction=("Write a blameless postmortem (markdown: summary, impact, timeline, root cause, what went "
                 "well, what went badly, 3 action items with owners) from:\n{investigation}\n"
                 "Then call write_postmortem with it."),
)

applier = LlmAgent(
    name="applier", model=MODEL, tools=[t.apply_remediation], **CB,
    instruction="Call apply_remediation with the proposal id you are given and report the result verbatim.",
)

root_agent = SequentialAgent(name="sre_v2", sub_agents=[collectors, investigator, scribe])
