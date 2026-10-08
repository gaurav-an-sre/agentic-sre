"""v1 - the single agent we built first (kept on purpose; see docs/ARCHITECTURE.md "what v1 taught us").

One LlmAgent, every tool, no callbacks. Investigation, remediation and write-up all happen in one
context. The safety rules live in the prompt - which is exactly the problem."""

from __future__ import annotations

import os

from google.adk.agents import LlmAgent

from agents.common import tools as t

MODEL = os.environ.get("SRE_MODEL", "gemini-2.5-flash")

root_agent = LlmAgent(
    name="sre_v1",
    model=MODEL,
    description="Single on-call SRE agent (v1).",
    instruction=(
        "You are the on-call SRE for a Thai e-commerce retailer. Investigate the page, find root cause, "
        "fix it and write it up. Please be careful: cite evidence and do not change production without "
        "a good reason."  # prompt-only control: nothing enforces it
    ),
    tools=[*t.READ_TOOLS, t.get_logs_raw, t.propose_remediation, t.apply_remediation_ungated, t.write_postmortem],
)
