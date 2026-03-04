# Phase 4 — Multi-Tenant Scheduler Hardening

## Goal
Move from single-tenant, best-effort scheduling to tenant-safe, fair, abuse-resistant scheduling with clear isolation controls and auditability.

## Milestones

### M4.1 Tenant Identity + Per-Tenant Quotas
- Add `tenant_id` to job persistence model.
- Require `X-Tenant-Id` on submit.
- Enforce per-tenant max running jobs in scheduler.
- Prove missing-tenant rejection and quota blocking.

### M4.2 Fair Scheduling Across Tenants
- Add tenant-aware fairness selection (round-robin or weighted RR).
- Prove alternating progress between active tenants.
- Prove no starvation when one tenant floods.

### M4.3 Tenant-Scoped Read Paths + Audit
- Enforce tenant isolation on `GET /jobs/{id}` and list paths.
- Persist audit metadata fields aligned with API flow.
- Prove cross-tenant reads are blocked.

### M4.4 Admission Control + Rate Limiting
- Add per-tenant submit throttling at API boundary.
- Add central validation caps (retries/timeout/resources).
- Prove deterministic throttling and robust scheduler behavior under burst.

### M4.5 Multi-Tenant Observability
- Add tenant-aware metrics/log fields with cardinality safeguards.
- Prove queue/running visibility by tenant (or safe aggregate strategy).
- Prove log correlation across `tenant_id` and `job_id`.

## Acceptance Criteria Checklist

### Evidence Pack Discipline
- Evidence location: `docs/evidence/phase4/m4.x/`
- Each milestone commit includes:
  - `runbook.md`
  - `commands.txt`
  - `outputs/` captures (`kubectl`, `curl`, `psql`, logs, tests)
- Update `docs/reflection.md` with:
  - what changed
  - what was proven
  - links to evidence files

### Deterministic Naming
- Use deterministic filenames:
  - `docs/evidence/phase4/m4.x/outputs/01-*.txt`
  - `docs/evidence/phase4/m4.x/outputs/02-*.txt`
- Avoid timestamps in filenames unless required for disambiguation.

### Repository Guardrails
- Do not modify Phase 3 evidence.
- Do not commit secrets.
- Use `.env.example` only when needed.

## Definition of Done (Per Milestone)

### M4.1 DoD
- `tenant_id` migration and scheduler query index exist.
- API rejects missing tenant identity.
- Per-tenant running cap enforced with proof outputs.

### M4.2 DoD
- Fair scheduling algorithm implemented and deterministic.
- Two-tenant test shows balanced progress and no starvation.

### M4.3 DoD
- Tenant cannot access another tenant's job details/listings.
- Audit fields are persisted and verifiable.

### M4.4 DoD
- Per-tenant throttling active with clear error behavior.
- Validation caps enforced with deterministic failures.
- Scheduler remains healthy under throttled load.

### M4.5 DoD
- Metrics/log signals reflect tenant-aware behavior.
- Correlation of `tenant_id` + `job_id` is visible and reproducible.

## Phase 4 Completion Criteria
- Tenant identity is mandatory and persisted.
- Scheduler enforces per-tenant concurrency.
- Fairness prevents starvation.
- Tenant read isolation is enforced.
- Abuse controls (throttle + caps) are active and observable.
- `docs/reflection.md` links all `M4.1`–`M4.5` evidence packs.
