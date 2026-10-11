# v1 post-mortem: what the single agent taught us

v1 was deliberately kept (`agents/v1/`) because its failures *are* the v2 design brief.
Every v2 mechanism below exists because a specific v1 behaviour broke against the
frozen incident bundle (`evidence/INC-2026-1009`) and later against live traffic.

## What v1 was

One ADK agent (`sre_v1`), every read tool plus `apply_remediation` in one context,
prompt-level instructions to be careful, no gates, no audit. `make v1` runs it.

## What it actually did wrong

| Failure | What we observed | v2 mechanism it forced |
|---|---|---|
| First-spike fixation | Anchored on the first 5xx spike, proposed `shift_traffic` on the *wrong* revision — never correlated the deploy that preceded it | Parallel collectors gather deploys/logs/metrics **before** any reasoning; the investigator must rule out alternatives and cite evidence |
| Context blow-up | Pulled raw log lines into context until deploy diffs scrolled out of the window; its "reasoning" degraded with context length | Collectors return *structured evidence with ids*, not raw text; the investigator never sees raw logs |
| Ungated apply | Called `apply_remediation` whenever the prompt felt confident — "be careful" is not a control | `before_tool_callback` blocks every production write at the framework level; `remediation-mcp` re-checks server-side |
| Unverifiable prose | Long narrative, no citations; nothing to check, nothing to replay | Citation validator rejects claims without evidence ids; the audit log records every call |
| No separation | Same context that investigated also had the write tool — a jailbreak away from an unreviewed production change | Applier is a *separate* agent/tool path behind the approval gate; the investigator structurally cannot reach it |
| No human in the loop | "Approval" was the agent saying the plan was fine | `pending_approval → human approves → applying → applied` in the shared proposal store; `POST /approve` is a human endpoint on a separate service account |

## The lesson that became the architecture

> The model proposes; code validates and decides; a human approves; the system logs and replays.

v1 was not a wasted build — it produced the evals. `evals/cases.json` grades v2 against
exactly these failures (cites the real culprit, exactly one proposal, zero apply attempts
pre-approval). v1 still fails those evals on purpose; that's the before/after evidence.
