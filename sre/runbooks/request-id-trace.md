# Runbook: trace one customer click end to end

Every request gets an `X-Request-ID` at the **storefront** edge (or reuses the caller's), which propagates storefront → checkout → payments-api → Cloud Logging. One shopper's click is one id.

## From a customer complaint
1. Ask for the request id shown on the storefront page (or take any failed checkout response's `X-Request-ID` header).
2. Log Explorer:
   ```
   jsonPayload.request_id="req_<id>"
   ```
   → all three services' structured access logs for that single request: status, latency_ms, and (payments-api) `db_pool_in_use`/`db_pool_waiting` at that moment.

## From an alert, finding the id
- Grafana/Monitoring shows *rates*; to see *a request*: Log Explorer with `severity>=ERROR AND resource.labels.service_name="<svc>"` → open any entry → its `request_id` → paste into the query above for the full hop-by-hop.

## Correlation rules
- Same `request_id` in checkout's `payments.jsonl` and `orders.jsonl` evidence = the business outcome of that call.
- A proposal's cited log entries all carry the ids it reasons about — you can re-derive any claim from Cloud Logging.
- Missing id at storefront but present downstream means the caller set it — trust it less (it's caller-controlled input; use it for correlation, not for auth).
