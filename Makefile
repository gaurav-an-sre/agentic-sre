PY := .venv/bin/python
export PYTHONPATH := system/checkout:.

setup:            ## venv + deps (no API key needed for tests)
	uv venv -q .venv && uv pip install -q -e ".[dev]"
test:             ## offline tests + lint
	.venv/bin/pytest -q && .venv/bin/ruff check agents tests evals
bundle:           ## regenerate + reseal the synthetic incident bundle
	cd evidence && ../$(PY) make_bundle.py
# --- the real system, locally -------------------------------------------------
up:               ## storefront + checkout on :8000
	$(PY) -m uvicorn checkout_svc.main:app --port 8000
shop:             ## deterministic shoppers against :8000
	$(PY) system/checkout/shopper.py --base-url http://localhost:8000
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
