# Runbook: payments-api 5xx spike / DB pool exhaustion

**Alert:** `payments-api HighErrorRate5xx` or SLO burn `availability fast(30m)`
**First question:** did a deploy precede this? (Most of these are a bad revision, not traffic.)

## 1. Confirm blast radius — 2 min
- Grafana dashboard `payments-api`: 5xx rate, RPS, p95.
- Cloud Monitoring: `run.googleapis.com/request_count` by `response_code_class` for service `payments-api`.

## 2. Did a deploy precede it? — 2 min
- Console: Cloud Run → `payments-api` → Revisions. Look at `createdTime` of the newest revision vs first error.
- Or the agent already did it: check the incident's proposal — `deployments` evidence cites `D-*` entries.
- `db_pool_in_use` / `db_pool_waiting` in the access logs: pool at `POOL_SIZE` and waiters climbing = pool config regression (our canned incident: `DB_POOL_SIZE` dropped 50 → 4 in `payments-api-00041`).

## 3. Mitigate — rollback, not debugging — 3 min
Last known good revision is the previous one that served traffic:
```
gcloud run services update-traffic payments-api \
  --region $REGION --project $PROJECT \
  --to-revisions payments-api-00040-xyz=100
```
Or approve the agent's proposal (`POST /approve` on `sre-trigger`) and let `remediation-mcp shift_traffic` do it.

## 4. Verify — 2 min
- 5xx rate returns to <1% within one traffic-shift propagation (~60s).
- `db_pool_waiting` back to 0.
- Confirm with PSP: no stranded transfers (idempotency keys mean a retried call replays safely).

## 5. Wrap
- Agent's scribe leaves a postmortem draft; human reviews within 24h.
- If this alert fires again within a week, the deploy pipeline needs a canary step — escalate to the platform owner, don't just keep rolling back.

## When NOT to rollback
- 5xx with *no* recent deploy and rising `db_pool_waiting` on the same revision → RDS/Cloud SQL connectivity or a traffic surge; check `cloudsql.googleapis.com` metrics first.
