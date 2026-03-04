# PHASE4 M4.Closeout Runbook

## Goal
Close out Phase 4 by verifying end-to-end platform behavior with no new feature changes.

## Scope
Verification-only milestone. No core logic changes are introduced.

## Prerequisites
- Python environment with project dependencies installed
- Repo at branch `feature/m4-closeout-e2e-verification`
- Existing Phase 4 evidence packs (`m4.1`..`m4.5`) present in `docs/evidence/phase4/`

## Environment knobs used for closeout verification
- `TENANT_MAX_RUNNING=1` (quota proof)
- `TENANT_SUBMIT_RPS=1` and `TENANT_SUBMIT_BURST=1` (rate limit proof)
- `SCHEDULER_METRICS_PORT=9000` (scheduler metrics scrape surface; local harness also probes a local metrics port)

## Procedure
1. Capture run surface map from README + operations docs.
2. Run evidence checks for all Phase 4 milestones (`m4.1` to `m4.5`).
3. Run lint and full unit-test suite.
4. Run lightweight deterministic harnesses that prove:
   - tenant isolation (`GET` cross-tenant returns `404`)
   - fairness + quota behavior (alternating dispatch + quota skip)
   - rate-limiting behavior (`429` burst + counter increment)
   - metrics scrape from API and scheduler metrics endpoint
5. Collect outputs under `docs/evidence/phase4/m4.closeout/outputs/`.

## Expected results
- All Phase 4 evidence checks pass.
- Lint + unit tests pass.
- Cross-tenant read is denied (`404`).
- Fairness dispatch order alternates for two tenants and quota blocks are observable.
- Burst submit shows `429` and increments rate-limit metric.
- Metrics scrape contains non-zero Phase 4 counters/gauges proving behavior.

## Output files
- `outputs/01-run-surface-map.txt`
- `outputs/02-phase4-evidence-checks.txt`
- `outputs/03-lint-and-tests.txt`
- `outputs/04-e2e-tenant-isolation.txt`
- `outputs/05-e2e-fairness-and-quota.txt`
- `outputs/06-e2e-rate-limit.txt`
- `outputs/07-e2e-metrics-scrape.txt`
