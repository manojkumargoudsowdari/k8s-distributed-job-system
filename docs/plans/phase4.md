# Phase 4 — Multi-Tenant Scheduler Hardening

Goal: move from "single-tenant / best-effort scheduling" to "tenant-safe, fair, abuse-resistant scheduling with clear isolation controls and auditability."

## Phase 4 deliverables (minimum "hardening")

### Multi-tenant identity
- Every job is bound to a tenant identity (`tenant_id`).
- API enforces tenant identity on submit; all reads are tenant-aware (at least filterable; ideally scoped).

### Tenant isolation + fairness
- Per-tenant concurrency quotas (max running per tenant).
- Fair scheduling across tenants (round-robin / weighted fairness).
- Per-tenant queue depth visibility and metrics.

### Safety & abuse controls
- Rate limiting / admission controls at API boundary (per tenant).
- Hard caps (max job size, max env vars, max payload).
- Strong validation + deterministic errors.

### Operational hardening
- Scheduler resilience under load (bounded DB queries, backpressure).
- Deterministic scheduling behavior with evidence.
- Auditable events (who submitted, tenant, idempotency key, etc.).

## Recommended implementation shape (fits this repo)
- Extend existing Job model with `tenant_id` and related indexes.
- Extend API middleware to extract/validate tenant identity from headers.
- Extend scheduler "next job selection" logic to be tenant-aware + fair.
- Keep evidence pack discipline identical to Phase 3, but under `docs/evidence/phase4/`.

## Phase 4 milestone sequence (in order)

### M4.1 Tenant identity + per-tenant quotas
- Add `tenant_id` to DB/job model.
- Require tenant in submit (`X-Tenant-Id`).
- Scheduler enforces per-tenant max running.
- Prove: missing tenant rejected; quota blocks overscheduling.

### M4.2 Fair scheduling across tenants (RR / weighted)
- Implement round-robin across active tenants (or weighted RR).
- Prove: two tenants alternate when both have pending jobs and quota available.
- Prove: no starvation when one tenant floods submissions.

### M4.3 Tenant-scoped read paths + audit fields
- Ensure list/get endpoints are tenant-scoped or tenant-filtered.
- Add audit fields: `submitted_by` (optional), request/idempotency reference, `created_from_ip` (optional if present).
- Prove: tenant cannot read another tenant's job; audit fields persisted.

### M4.4 Admission control + rate limiting (API boundary)
- Add per-tenant rate limiting on submit (token bucket or sliding window).
- Add maximums (max retries, max timeout, max resources) enforced centrally.
- Prove: burst throttled; invalid specs rejected; scheduler remains stable.

### M4.5 Observability for multi-tenant behavior
- Add per-tenant metrics (with cardinality safeguards: cap/hash/aggregate where needed).
- Add logs with `tenant_id` correlation.
- Prove: metrics reflect per-tenant queue depth/running, quota blocks, throttles.

---

## Phase 4 acceptance criteria checklist (evidence-pack driven)

Use this as the Definition of Done for each Phase 4 milestone. Each milestone ends with one clean commit that includes code + manifests + docs + evidence.

### Global rules (apply to every milestone)

#### Evidence pack location
- `docs/evidence/phase4/m4.x/`

#### Every milestone commit must include
- `runbook.md` (exact steps + expected outputs)
- `commands.txt` (copy/paste commands)
- `outputs/` (captured outputs: `kubectl`/`curl`/`psql`/logs/tests)

#### Reflection updated
- Update `docs/reflection.md` with:
  - what changed
  - what was proven
  - links to evidence files

#### Naming convention
- `docs/evidence/phase4/m4.x/outputs/01-*.txt`, `02-*.txt`, `03-*.txt` (deterministic)
- Avoid timestamps in filenames unless necessary.

#### Do not
- Modify Phase 3 evidence.
- Commit secrets (`.env`), only `.env.example`.

## Definition of Done by milestone

### M4.1 — Tenant identity + per-tenant concurrency quotas
#### Must build
- DB migration adding `tenant_id` to jobs (+ index supporting scheduler queries).
- API requires `X-Tenant-Id` on submit; persists `tenant_id`.
- Scheduler enforces `TENANT_MAX_RUNNING` (config).

#### Must prove (evidence)
- Migration applied successfully; schema shows `tenant_id` + indexes.
- Submit without tenant is rejected (or safe dev default is documented).
- Submit with tenant succeeds and `tenant_id` is stored.
- Quota enforcement: tenant hits max running; extra jobs remain queued.

#### Required evidence files (`outputs/`)
- `01-repo-structure.txt`
- `02-db-migration-status.txt`
- `03-api-tenant-validation.txt`
- `04-scheduler-tenant-quota.txt`
- `05-tests.txt`

#### Pass condition
- Reviewer can reproduce: tenant required + quota blocks overscheduling.

### M4.2 — Fair scheduling across tenants
#### Must build
- Scheduler chooses next job using RR (or weighted RR) across tenants with pending jobs and available quota.

#### Must prove (evidence)
- With two tenants and N queued jobs each, scheduling alternates tenants (or respects weights).
- No starvation when one tenant floods submissions.

#### Required evidence files (`outputs/`)
- `01-setup-two-tenants.txt`
- `02-round-robin-proof.txt`
- `03-no-starvation-proof.txt`
- `04-scheduler-logs-fairness.txt`
- `05-tests.txt`

#### Pass condition
- Clear, repeatable fairness behavior demonstrated.

### M4.3 — Tenant-scoped read paths + audit
#### Must build
- List/get endpoints enforce tenant scoping (no cross-tenant reads).
- Persist audit metadata aligned with existing patterns.

#### Must prove (evidence)
- Tenant A cannot read tenant B `job_id`.
- Tenant scoping works for list queries.
- Audit fields visible in DB and/or API response.

#### Required evidence files (`outputs/`)
- `01-cross-tenant-read-denied.txt`
- `02-tenant-list-filter.txt`
- `03-db-audit-fields.txt`
- `04-tests.txt`

#### Pass condition
- Data isolation is demonstrably correct.

### M4.4 — Admission control + rate limiting
#### Must build
- Per-tenant rate limit on submit.
- Central validation caps (timeout/retries/resources/etc.).
- Backpressure behavior documented.

#### Must prove (evidence)
- Burst submissions are throttled deterministically.
- Oversized/invalid specs are rejected with clear errors.
- Scheduler remains healthy under stress.

#### Required evidence files (`outputs/`)
- `01-rate-limit-burst.txt`
- `02-validation-caps.txt`
- `03-scheduler-stability-under-load.txt`
- `04-metrics-or-logs-during-throttle.txt`
- `05-tests.txt`

#### Pass condition
- Abuse controls work and are observable.

### M4.5 — Multi-tenant observability
#### Must build
- Metrics/logs include tenant-aware signals (with label-cardinality safeguards).
- Dashboards optional; metrics proof required.

#### Must prove (evidence)
- Metrics show per-tenant queued/running (or a documented safe aggregated version).
- Logs correlate `job_id` + `tenant_id`.
- Evidence run shows fairness + quota reflected in metrics.

#### Required evidence files (`outputs/`)
- `01-metrics-baseline.txt`
- `02-metrics-two-tenants-load.txt`
- `03-metrics-after-drain.txt`
- `04-logs-correlation-tenant.txt`

#### Pass condition
- Reviewer can validate multi-tenant behavior via metrics/logs.

## Final Phase 4 completion criteria
- Tenant identity is mandatory and persisted.
- Scheduler enforces per-tenant concurrency limits.
- Fair scheduling prevents starvation.
- Tenant read isolation is enforced.
- Rate limiting + admission caps prevent abuse.
- `docs/reflection.md` links evidence packs for `M4.1`–`M4.5`.
