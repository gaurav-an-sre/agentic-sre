# Handover notes — pairing with the client's platform engineer

Written to be read by the person who owns this after the engagement. Worked through together,
not handed over blind — every section below was paired on (they drove, I reviewed) before sign-off.

## What you own now

| Piece | Where | Your job |
|---|---|---|
| SLOs | `sre/slo.yaml` | Monthly review; change a number → run `31_slos.sh` |
| Runbooks | `sre/runbooks/` | Update after every real incident — if the runbook didn't help, the runbook is wrong |
| The agent squad | `agents/v2` on Agent Engine | Retrain on new incident bundles; v1 (`agents/v1`) stays as the cautionary baseline |
| The control plane | `mcp_servers/` + `agents/common/control_plane.py` | The rules are code, not prompts. Changing a gate = a code review + evals run |
| Approvals | `POST /approve` on `sre-trigger` | Only humans hold `X-Approve-Token` (Secret Manager, `sre-trigger` SA). Never give it to the agent identity |
| The red button | `80_red_button.sh` / `make red-button` | Use it first, ask later |

## The three rules we agreed on

1. **The agent reads; code decides; humans approve.** Any request to "let the agent just do X automatically" gets an eval-bundle run first. Widening autonomy is an evidence decision, not a vibes decision.
2. **Proposals without evidence ids are bugs.** If the investigator starts asserting without citations, that's a regression — check `evals/` before trusting it.
3. **New alert class ⇒ new runbook + new eval case.** `evals/cases.json` is the gate for every autonomy change. Frozen bundle per incident (`make bundle` → `make evals`).

## Standing questions to revisit quarterly

- Does `order_success` still reflect what customers feel? (We picked 98% — was it right?)
- Are proposals being approved ≥80% of the time? Below that, the evidence quality has drifted.
- Still at autonomy L2? Moving to L3 (bounded auto-rollback for the *bad-deploy* alert class only) requires 90 days of clean proposals.
