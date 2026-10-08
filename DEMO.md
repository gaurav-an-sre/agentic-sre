# Demo walk-through (local, ~8 min)

**0. The system.** `make up` then `make shop` in a second tab. Storefront at http://localhost:8000 - orders succeed.
`make break-promo`: free-shipping promo deployed; `/healthz` stays green, ~40% of carts now decline
(pricing applies free shipping, the independent authorisation still adds flat shipping - a 999-cent mismatch
the provider rejects without an exception). This is the "green dashboards, angry customers" incident.
`make rollback-promo` to recover. The payments-api pool incident is the same idea at the Cloud Run layer
(`system/scripts/40_break.sh` once a project is set).

**1. v1 - one agent.** `make v1`. Watch for: it opens `get_logs_raw`, it talks about the cache-node restart,
and under pressure it calls `apply_remediation_ungated`. Say: "this is where we stopped trusting prompts."

**2. v2 - squad + control plane.** `make v2`. Three collectors run in parallel and return bullets with ids;
the investigator builds a timeline, rules out the cache node, cites `D-7740` + PoolTimeout lines, and calls
`propose_remediation` once -> `P-xxxx pending_approval`. The scribe writes `postmortems/INC-2026-1009.md`.

**3. The gate.** `make apply P=P-xxxx` -> `PolicyDeny` (proposal not approved). `make audit` shows the line.

**4. Human.** `make approve P=P-xxxx` (no model involved; writes the approval record).
`make apply P=P-xxxx` -> simulated rollback to `payments-api-00041-kqd` (real `gcloud run services
update-traffic` when the bundle came from a project).

**5. Proof.** `make evals` (v2) and `make evals` with `v1` to compare: v1 fails `no_unapproved_apply` on
the pressure case; v2 passes all three.

## Deploying the real system (later)
```zsh
export PROJECT=<gcp project id> REGION=asia-southeast1
cd system/scripts && ./00_enable_apis.sh && ./10_provision.sh && ./20_deploy.sh v2.14.2 50 5000 && ./30_alerts.sh
./40_break.sh && ./50_loadgen.sh                 # bad revision + traffic, dashboard red in ~2 min
python evidence/gcp_snapshot.py snapshot --project $PROJECT   # -> evidence/INC-<ts>/
export SRE_BUNDLE=evidence/INC-<ts>; make v2 ...  # apply now shifts real traffic, approval still required
./60_rollback.sh; ./90_teardown.sh
```
Agent Engine: `agents/v2/deploy_agent_engine.py` (needs `pip install -e ".[gcp]"` and the project).
