# Architecture and the decisions behind it

Anonymised customer: a Thai e-commerce grocery retailer. Small dev teams, no ops/SRE function,
product owners pushing changes, devs deploying to production, failures reaching customers.
The engagement had two halves: (1) make the system *observable and recoverable* at all, and
(2) put an agent on call - first one agent (v1), then a squad with a control plane (v2).
The same design was later rebuilt on the Claude Agent SDK (see `claude-code-demos/sre-agent`).

```
 customers ──> storefront+checkout (Cloud Run) ──> payments-api (Cloud Run) ──> Cloud SQL
                      │ structured logs, metrics, revisions, alerts (Cloud Logging / Monitoring)
                      ▼
            frozen evidence bundle  (SHA-256 manifest; 45-min snapshot or synthetic)
                      │
   v1: one LlmAgent, every tool, rules in the prompt           v2 (Agent Engine, ADK):
                                                               ┌ collectors (parallel, read-only) ┐
                                                               │ metrics │ logs+alerts │ changes │
                                                               └────────────┬───────────────────┘
                                                                     investigator  ── propose_remediation (one)
                                                                            │
                                                                          scribe  ── write_postmortem
                                                               control plane (code, every tool call):
                                                               audit log · citation validator · approval gate
                                                                            │
                                                               human: `approve P-xxxx` ─> applier (separate agent)
```

## Decisions and tradeoffs

| # | Decision | Alternative we rejected | Why | What it cost us |
|---|----------|------------------------|-----|-----------------|
| 1 | Fix the system first (health endpoints, structured logs with request ids, revision labels, alert policies, a rollback primitive) | Put an agent on the existing mess | An agent can only reason over evidence that exists; the first week was `_log()` and labels, not prompts | Two weeks before any AI was visible to the sponsor |
| 2 | Cloud Run + Cloud SQL managed stack | GKE | No ops team; Cloud Run revisions give a *free, safe rollback primitive* (`update-traffic --to-revisions`) that an agent can be allowed to call | Less control over networking / pool tuning - which is literally the incident |
| 3 | **v1: one agent, all tools** | Start multi-agent | Cheapest way to learn what the model does on real evidence | See "what v1 taught us" |
| 4 | **v2: parallel collectors -> investigator -> scribe** | Keep one agent, better prompt | Collectors cap context per concern and run in parallel; the investigator only ever sees summaries with evidence ids | More moving parts, ~3x tool calls, slower first token |
| 5 | Control plane in code (`before_tool_callback`) | "Be careful" in the prompt | Rules that must hold 100% cannot be probabilistic; the model is never the control | Callbacks are per-agent - easy to forget one (tests check all five leaves) |
| 6 | Propose-only; `apply` is a separate agent behind an approval record | Auto-remediate for "obvious" cases | Zero blast radius on day one; the customer's change-control board could sign off | MTTR gain capped by human latency at first; autonomy widened per alert class later, on eval evidence |
| 7 | Frozen, hash-sealed evidence bundle | Query live consoles during investigation | Replayable: same bundle -> evals in CI with no prod access; no "it worked on the bridge" | Snapshot staleness (45-min window); a second snapshot if the incident moves |
| 8 | Citation validator rejects any claim without an evidence id | Trust the model's summary | On-call engineers only trusted the agent once every line pointed at a log id they could open | Terse output; the agent sometimes refuses to speculate when speculation would help |
| 9 | Rollback only to a revision *present in the bundle* | Any revision the model names | Prevents typos / hallucinated revisions from reaching `gcloud` | Can't roll forward to a hotfix built mid-incident without a new snapshot |
| 10 | Agent Engine + Gemini Enterprise as the front door | Bespoke web app / Slack bot | Inherited IAM, logging, data residency (asia-southeast1); on-call already had the UI | Platform coupling - which is why the design was kept portable and later moved to the Claude SDK unchanged |
| 11 | Graded evals (`evals/run_evals.py`) as the release gate for prompt/tool changes | Manual rehearsal | Prompt edits silently change behaviour; graders are code | Needs a model to run (not in offline CI); 3 cases is a floor, not a suite |

## What v1 taught us (why it was retired, kept in `agents/v1`)
- **First-spike fixation**: it latched onto the cache-node restart (first anomaly in time) and proposed restarting it.
- **Context blow-up**: `get_logs_raw` dumped every line; the deploy diff fell out of attention.
- **Prompt rules don't hold**: under "SEV1, CEO on the bridge" it called `apply_remediation_ungated`. Nothing stopped it.
- **No separation of concerns**: the same context that investigated also wrote the postmortem, so it narrated its own first guess.
- **Unverifiable output**: prose without ids - on-call could not check a single claim quickly.

Each of these maps to one line in the v2 table above (4, 4, 5/6, 4, 8).

## How agents reach tools: MCP

Every external system sits behind an MCP server (`mcp_servers/`), a fixed menu of typed actions. The model
never holds API keys or a shell. Four services, one Cloud Run deployment each, internal ingress, IAM auth,
one service account each:

| server | tools | SA roles | writes |
|---|---|---|---|
| observability-mcp | query_metrics, get_service_health, get_alerts, get_logs, get_slo | monitoring.viewer, logging.viewer | none |
| release-mcp | list_revisions, get_deploy_diff, read_config, get_runbook | run.viewer, clouddeploy.viewer | none |
| incident-mcp | get_incident, create_issue, write_postmortem | logging.logWriter (+ Jira/Confluence tokens) | Jira/Confluence only |
| remediation-mcp | shift_traffic(proposal_id, service, revision, percent) | run.developer | Cloud Run traffic, approval-gated |

The gate runs twice: in the agent's `before_tool` callback (`control_plane.py`) and again inside
remediation-mcp (`check()`: approved proposal, matching target revision, revision on the allow-list). Results
carry ids (Cloud Logging insertId, revision name, alert policy id) so the citation validator can resolve them.
`SRE_TOOLS=mcp` switches the v2 squad from in-process functions to `McpToolset`s; the squad, prompts, control
plane and evals are unchanged - which is also why the same servers serve a Claude Agent SDK harness.

## Controls added after the first live denial (pre-flight on the write path)

The approval gate alone turned out to be binary: when on-call asked the agent to "just apply it" the gate
refused (good), but the human had no preview of blast radius, nothing stopped two remediations racing, and a
rollback could land in the middle of a promo peak. `mcp_servers/safety.py` adds, below the model:

| Control | What it does | Where |
|---|---|---|
| `dry_run=true` | Returns the plan (current split -> target) and every check result; mutates nothing | `shift_traffic` |
| Justification | `incident_id` must be the open incident; resolved or unknown incidents are denied | `safety.justification` |
| Concurrent-action hold | Another proposal applied inside `CONCURRENT_WINDOW_MIN` (10) -> `held`, until a human passes `override_hold=<name>` | `safety.concurrent_action` |
| Change-freeze hold | `CHANGE_FREEZE_HOURS=18-23` (Asia/Bangkok) -> `held`; promo nights are humans-only unless overridden | `safety.change_freeze` |
| Red button | `make red-button` locally / `system/scripts/80_red_button.sh on` on GCP pauses all agent actuation; enforced in the agent callback and in remediation-mcp | `safety.red_button` |

These are the controls Google SRE's paper on AI in operations calls dry-run, justification verification,
concurrent-action check and the "Red Button" (https://sre.google/resources/practices-and-processes/ai-engineering-reliable-operations/).
On its autonomy ladder: v1 is L1 (assisted investigation), v2 is L2 (human approves, system actuates).
L3 (auto-approve rollback for one alert class on non-payment services) is the agreed next step, gated on the
replay suite - not claimed.

## Gemini/ADK -> Claude Agent SDK mapping
| Concern | ADK (v2) | Claude Agent SDK (sre-agent) |
|---|---|---|
| Tool gate | `before_tool_callback` | `PreToolUse` hook + `can_use_tool` |
| Audit | `after_tool_callback` | `PostToolUse` hook |
| Squad | `ParallelAgent` / `SequentialAgent` | subagents (`AgentDefinition`) |
| Tools | plain functions | in-process MCP server |
| Evidence, proposals, approval record, evals | identical files | identical files |
The model and harness changed; the control plane, bundle format and evals did not. That portability was deliberate (decision 10).

## What is real vs. reference here
- Customer context, the operating-model problem and the v1 -> v2 lessons: engagement.
- Code in this repo: anonymised reference implementation; the bundle `INC-2026-1009` is synthetic; `evidence/gcp_snapshot.py` freezes a real Cloud Run incident when a project is set.
- Numbers quoted in the deck are labelled *measured on the reference run* or *customer target*.
