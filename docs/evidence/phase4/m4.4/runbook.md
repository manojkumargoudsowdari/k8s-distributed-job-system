# PHASE4 M4.4 Runbook

## Goal
Add API admission control and per-tenant submit throttling without changing scheduler behavior.

## Steps
1. Inspect API submit path, tenant validation, idempotency handling, config/env usage, and DB create path.
2. Implement in-memory per-tenant token bucket limiter on POST /jobs.
3. Enforce submit hard caps (payload size, env limits, retries cap, timeout cap).
4. Add unit tests for throttling, tenant isolation in throttling, cap violations, and non-regression.
5. Capture deterministic evidence outputs 01-06.
6. Run lint, unit tests, and scripts/evidence_check.sh phase4 m4.4.

## Expected Results
- Over-limit submit requests return 429 with deterministic detail and Retry-After.
- Tenant throttling is isolated per tenant.
- Oversized/invalid payloads are rejected deterministically.
- Throttled submits do not persist DB rows; accepted submits still persist normally.
- Evidence check passes.
