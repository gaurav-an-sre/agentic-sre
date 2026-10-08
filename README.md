# agentic-sre-thai-retail

A Thai e-commerce retailer (anonymised) with small dev teams and no ops function kept shipping
changes that broke production. This repo is the reference implementation of what we built with them:

1. **`system/`** - the real stack: storefront + checkout (FastAPI, promo-config incident where health is
   green but checkouts fail), `payments_api` (Cloud Run + Cloud SQL, pool-size regression), load generator,
   and `scripts/` to provision / deploy / break / roll back on GCP (`PROJECT=<id>` - nothing runs until you do).
2. **`evidence/`** - frozen, SHA-256-sealed incident bundles. `make_bundle.py` builds the synthetic one;
   `gcp_snapshot.py` freezes the last 45 min of Monitoring / Logging / revisions from a real project.
3. **`agents/v1`** - the single ADK agent we started with. No gates. Kept to show why.
4. **`agents/v2`** - ADK multi-agent (parallel collectors -> investigator -> scribe) with the control plane
   in code: audit log, citation validator, approval-gated apply.
5. **`evals/`** - graded replays over the frozen bundle.

Read `docs/ARCHITECTURE.md` for the decisions and tradeoffs, `DEMO.md` for the walk-through.

```zsh
make setup && make test          # offline: no API key, no GCP
export GOOGLE_API_KEY=...        # or GOOGLE_GENAI_USE_VERTEXAI=1 GOOGLE_CLOUD_PROJECT=... GOOGLE_CLOUD_LOCATION=asia-southeast1
make v1                          # watch it fixate / dump logs / try to apply
make v2                          # collectors -> investigator proposes P-xxxx -> scribe
make apply P=P-xxxx              # PolicyDeny (not approved)
make approve P=P-xxxx && make apply P=P-xxxx
make audit
```
