# Runbook: checkout declines / "green dashboards, angry customers"

**Alert:** SLO burn `checkout/order_success` — or customers call before any alert (this SLO exists because infra stayed green while orders failed).
**Signature:** 2xx responses, pods healthy, but `decline_rate` climbing; `amount_mismatch` in `var/payments.jsonl` or Cloud Logging.

## 1. Confirm it's the promo/config path — 2 min
- Log Explorer: `jsonPayload.reason="amount_mismatch" AND resource.labels.service_name="checkout"`.
- Look at `requested_amount_cents` vs `reconciliation_amount_cents` — a constant gap (e.g. 999c) = a pricing/config regression, not a PSP outage.
- Get one `request_id` from an affected order and trace it storefront → checkout → payments-api (see `request-id-trace.md`).

## 2. Check what changed — 2 min
- `promo.yaml`/`checkout` config diffs: a free-shipping campaign that drops the fee line the PSP expects is the canned failure.
- Cloud Run revision history for `checkout` — same-day deploy?

## 3. Mitigate
- Bad promo config → revert the config file / redeploy previous revision (checkout config is baked at deploy).
- If unclear, **pause the campaign**, not the service — declining orders is better than charging wrong amounts.
- The agent's proposal for this class is *never* `shift_traffic` on payments — the money path is fine; the bug is upstream arithmetic.

## 4. Verify
- `order_success` back to ≥98% over 15 min.
- Spot-check one real order end-to-end with the PSP.

## Why this runbook exists
Every health check was green during the canned incident — only the business SLO caught it. If you get paged here, trust the decline signal over the green dashboard.
