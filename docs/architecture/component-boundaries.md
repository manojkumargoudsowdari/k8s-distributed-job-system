# Component Boundaries

## Responsibilities

### API Service (`services/api`)
- Owns external HTTP contract: submit, get, list, cancel, health, metrics.
- Validates request shape and required headers (`Idempotency-Key`, `X-Tenant-Id` for submit).
- Persists and reads job state through repository APIs only.
- Must return deterministic error responses for invalid requests or contract conflicts.

### Scheduler Service (`services/scheduler`)
- Owns reconcile loop from persisted desired state to execution state.
- Selects dispatchable jobs from Postgres, applies runtime gates (retry/backoff/tenant quota), and creates Kubernetes Jobs.
- Reconciles Kubernetes outcomes into terminal Postgres state.
- Handles timeout/stuck-job recovery and retry requeue transitions.

### DB/Repository Layer (`pkg/job_system/db.py`, `db/migrations`)
- Owns authoritative state machine persistence and transition guardrails.
- Owns query interfaces for dispatchable selection, running counts, and metrics rollups.
- Owns schema evolution through SQL migrations in `db/migrations/`.

### Kubernetes Execution Substrate
- Owns actual container execution for dispatched `batch/v1 Job` workloads.
- Provides runtime status and pod logs/events observed by scheduler and operators.
- Does not own authoritative business state; execution truth is reconciled into Postgres.

## Anti-Responsibilities

### API Must Not
- Create Kubernetes Jobs directly.
- Infer final execution state from in-memory assumptions.
- Bypass repository transition semantics with raw ad hoc SQL in handlers.

### Scheduler Must Not
- Accept public client traffic or own API request validation.
- Store canonical lifecycle state in memory only.
- Mutate DB state outside repository transition methods.

### DB Layer Must Not
- Contain Kubernetes API calls.
- Encode HTTP routing/transport concerns.

### Kubernetes Must Not
- Be treated as the source of truth for product-level job lifecycle history.

## Public Interfaces (Current)

### API Endpoints (names only)
- `POST /jobs`
- `GET /jobs/{job_id}`
- `GET /jobs`
- `POST /jobs/{job_id}/cancel`
- `GET /healthz`
- `GET /metrics`

### Scheduler Loop Inputs/Outputs
- Inputs:
  - Dispatchable jobs query from Postgres (status/retry-gated).
  - Running job rows for completion/timeout reconciliation.
- Outputs:
  - Kubernetes `Job` create/get/list/delete operations.
  - Postgres state transitions (`QUEUED -> RUNNING -> SUCCEEDED/FAILED` or retry requeue).

### Schema Source of Truth
- `db/migrations/*.sql` defines all schema changes.
- `jobs` table and related indexes are the canonical persistence contract for runtime state.
