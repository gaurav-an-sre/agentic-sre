# Runbook: payments-api rollback
1. Confirm the faulty deploy id and change ticket.
2. `deployctl rollback payments-api --to <previous-version>` (requires approval from on-call lead).
3. Watch http_5xx_rate and db_pool_wait_ms for 5 minutes.
4. Open a postmortem.
