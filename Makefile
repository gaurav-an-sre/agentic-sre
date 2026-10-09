PY := .venv/bin/python
export PYTHONPATH := system/checkout:.

setup:            ## venv + deps (no API key needed for tests)
	uv venv -q .venv && uv pip install -q -e ".[dev]"
test:             ## offline tests + lint
	.venv/bin/pytest -q && .venv/bin/ruff check agents tests evals mcp_servers
bundle:           ## regenerate + reseal the synthetic incident bundle
	cd evidence && ../$(PY) make_bundle.py
# --- the real system, locally -------------------------------------------------
up:               ## storefront + checkout on :8000
	$(PY) -m uvicorn checkout_svc.main:app --port 8000
shop:             ## deterministic shoppers against :8000
	$(PY) system/checkout/shopper.py --url http://localhost:8000
break-promo:      ## deploy the free-shipping promo (green health, failing checkouts)
	$(PY) system/checkout/deploy.py promo
rollback-promo:
	$(PY) system/checkout/deploy.py rollback
# --- agents -------------------------------------------------------------------
v1:               ## single agent, no gates (needs GOOGLE_API_KEY or Vertex env)
	$(PY) -m agents.v1.run investigate "PagerDuty: customers report failed transfers; payments-api error rate elevated"
v2:               ## multi-agent + control plane
	$(PY) -m agents.v2.run investigate "PagerDuty: customers report failed transfers; payments-api error rate elevated"
approve:          ## make approve P=P-xxxx
	$(PY) -m agents.v2.run approve $(P)
apply:
	$(PY) -m agents.v2.run apply $(P)
evals:
	$(PY) -m evals.run_evals
audit:
	tail -n 20 audit/tool_calls.jsonl
red-button:       ## pause all agent actuation locally (make red-button-off to resume); GCP: system/scripts/80_red_button.sh on|off
	echo "pressed $$(date -u +%FT%TZ) by $$USER" > audit/RED_BUTTON
red-button-off:
	rm -f audit/RED_BUTTON
# --- MCP servers locally (bundle source) --------------------------------------
mcp-%:            ## make mcp-observability | mcp-release | mcp-incident | mcp-remediation  (PORT=8081..)
	$(PY) -m mcp_servers $*
# --- GCP (needs PROJECT=...) ---------------------------------------------------
deploy-system:    ## APIs, Cloud SQL, payments-api, checkout, alerts, dashboard, Grafana, PagerDuty channel
	for s in 00_enable_apis 10_provision 20_deploy 22_deploy_checkout 30_alerts 35_dashboard 32_grafana 34_pagerduty; do system/scripts/$$s.sh || exit 1; done
deploy-mcp:       ## 4 MCP servers on Cloud Run, one SA each, internal ingress
	system/scripts/70_mcp_servers.sh
deploy-agent:     ## v2 squad on Vertex AI Agent Engine + PagerDuty webhook trigger
	$(PY) agents/v2/deploy_agent_engine.py && system/scripts/75_trigger.sh
