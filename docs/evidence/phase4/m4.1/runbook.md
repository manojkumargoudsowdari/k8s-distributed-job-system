# M4.1 Runbook — Tenant Identity + Per-Tenant Quotas

## Goal
Implement tenant identity as a mandatory submit attribute and enforce per-tenant scheduler concurrency (`TENANT_MAX_RUNNING`).

## Preconditions
- Branch: `feature/m4.1-tenant-identity-quotas`
- Docker Desktop running (for local Postgres evidence)
- Python dependencies available for API/scheduler tests

## Steps
1. Inspect repo structure and identify API/scheduler/DB/model/test integration points.
2. Add migration for `tenant_id` and tenant-aware indexes.
3. Update model + DB repository methods to persist and query tenant identity.
4. Enforce `X-Tenant-Id` in API submit path with deterministic validation errors.
5. Enforce per-tenant running quota in scheduler dispatch loop.
6. Add unit tests for tenant header enforcement/persistence and scheduler quota gate.
7. Capture deterministic evidence outputs in `outputs/01` ... `outputs/05`.
8. Update reflection with M4.1 proof links.

## Expected Proof
- Missing tenant header is rejected.
- Successful submit persists `tenant_id`.
- With `TENANT_MAX_RUNNING=1`, scheduler dispatches only one running job per tenant while others remain queued.
