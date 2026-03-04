# PHASE4 M4.5 Runbook

## Goal
Provide multi-tenant observability for fairness/quota/rate-limit behavior with safe Prometheus cardinality.

## Steps
1. Inspect metrics and logging surfaces in API, scheduler, and shared metrics module.
2. Add tenant-aware metrics using hashed tenant buckets (	enant_bucket=0..f).
3. Add API rate-limit metric increments and tenant-correlated API logs.
4. Add scheduler dispatch/quota decision counters and tenant-correlated scheduler logs.
5. Capture deterministic metrics and logs evidence outputs 01-05.
6. Run lint/tests and evidence check (outputs 06-07).

## Expected Results
- /metrics exposes new multi-tenant metric names at baseline.
- Two-tenant activity changes queued/running and dispatch decision metrics.
- Quota skip and API throttling increment dedicated counters.
- API and scheduler logs include tenant correlation on key decision lines.
- Evidence check passes.

## Cardinality strategy
- Raw 	enant_id is not used as a metrics label.
- Metrics use bounded hashed buckets (	enant_bucket=0..f) for tenant-aware observability.
