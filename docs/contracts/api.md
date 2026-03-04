# API Contract

## Purpose and Scope
This API is the control-plane interface for job submission and lifecycle reads in the distributed job system.

It provides:
- Job submission with tenant identity and optional idempotency.
- Job retrieval/listing.
- Queued-job cancellation.
- Health and metrics endpoints for operations.

It does not provide:
- Direct worker/container execution control by clients.
- Direct Kubernetes Job CRUD as a public API.
- Full authN/authZ system beyond tenant-header isolation.

## Global Rules

### Required Header
- `X-Tenant-Id` is required for:
  - `POST /jobs`
  - `GET /jobs/{job_id}`
  - `GET /jobs`
  - `POST /jobs/{job_id}/cancel`
- Validation rule: must match `^[A-Za-z0-9_-]{1,64}$`.

Optional submit metadata headers:
- `X-Submitted-By`
- `X-Request-Id`

### Content Type
- `POST /jobs` expects `Content-Type: application/json`.

### Idempotency
- Supported on `POST /jobs` via optional `Idempotency-Key` header.
- Behavior:
  - same key + same request fingerprint + same tenant -> returns existing `job_id`.
  - same key reused with different payload -> `409 Conflict`.
  - same key reused across different tenant -> `409 Conflict`.

### Admission Control and Throttling (POST /jobs)
- Per-tenant in-memory token bucket limiter:
  - `TENANT_SUBMIT_RPS` (default `2`)
  - `TENANT_SUBMIT_BURST` (default `5`)
- Hard submit caps:
  - `JOB_SUBMIT_MAX_PAYLOAD_BYTES` (default `16384`)
  - `JOB_SUBMIT_MAX_ENV_VARS` (default `64`)
  - `JOB_SUBMIT_MAX_ENV_KEY_LENGTH` (default `128`)
  - `JOB_SUBMIT_MAX_ENV_VALUE_LENGTH` (default `2048`)
  - `JOB_SUBMIT_MAX_RETRIES` (default `10`)
  - `JOB_SUBMIT_MAX_TIMEOUT_SECONDS` (default `86400`)
- Throttle response:
  - `429 Too Many Requests`
  - body: `{"detail":"Tenant submit rate limit exceeded; retry later"}`
  - header: `Retry-After: <seconds>`

### Base URL (Local/Dev)
- Typical local dev URL (with port-forward): `http://127.0.0.1:18080`
- In-cluster service: `job-system-api.default.svc.cluster.local:80` -> container port `8000`.

## Endpoint Catalog

| Method | Path | Description | Tenant/Header Requirement | Success Codes |
|---|---|---|---|---|
| `GET` | `/healthz` | Liveness/readiness health probe | None | `200` |
| `GET` | `/metrics` | Prometheus metrics | None | `200` |
| `POST` | `/jobs` | Submit a new job | `X-Tenant-Id` required, `Idempotency-Key` optional | `201` |
| `GET` | `/jobs/{job_id}` | Get one job by id | `X-Tenant-Id` required (tenant-scoped) | `200` |
| `GET` | `/jobs?status=&limit=` | List jobs with optional status filter and limit | `X-Tenant-Id` required (tenant-scoped) | `200` |
| `POST` | `/jobs/{job_id}/cancel` | Cancel queued job | `X-Tenant-Id` required (tenant-scoped) | `200` |

## Detailed Endpoint Specs

### GET `/healthz`
Example request:
```bash
curl -s http://127.0.0.1:18080/healthz
```
Success response:
```json
{"status":"ok"}
```

### GET `/metrics`
Example request:
```bash
curl -s http://127.0.0.1:18080/metrics | grep job_system_
```
Success response: Prometheus text exposition.

### POST `/jobs`
Example request:
```bash
curl -s -X POST http://127.0.0.1:18080/jobs \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: team_alpha" \
  -H "X-Submitted-By: alice" \
  -H "X-Request-Id: req-001" \
  -H "Idempotency-Key: submit-001" \
  -d '{
    "image":"busybox:1.36",
    "command":["sh","-c"],
    "args":["echo hello; exit 0"],
    "queue":"default",
    "max_retries":1,
    "backoff_seconds":5
  }'
```

Success response (`201`):
```json
{"job_id":"<uuid>","status":"QUEUED"}
```

Failure examples:
- Missing tenant header (`400`):
```json
{"detail":"X-Tenant-Id header is required"}
```
- Invalid tenant header (`400`):
```json
{"detail":"X-Tenant-Id must match ^[A-Za-z0-9_-]{1,64}$"}
```
- Idempotency conflict (`409`):
```json
{"detail":"Idempotency-Key conflict: request body differs from existing job"}
```
- Throttled (`429`):
```json
{"detail":"Tenant submit rate limit exceeded; retry later"}
```
- Admission cap violation (`400`):
```json
{"detail":"max_retries exceeds JOB_SUBMIT_MAX_RETRIES (10)"}
```

### GET `/jobs/{job_id}`
Example request:
```bash
curl -s http://127.0.0.1:18080/jobs/<job_id> \
  -H "X-Tenant-Id: team_alpha"
```
Success response (`200`) fields include:
- `id`, `tenant_id`, `status`, `attempts`
- audit fields (`submitted_by`, `request_id`, `created_from_ip`)
- spec fields (`image`, `command`, `args`, `env`, `resources`, `queue`, `priority`)
- retry/runtime fields (`max_retries`, `backoff_seconds`, `timeout_seconds`, `last_error`, `next_retry_at`)
- timestamps (`created_at`, `queued_at`, `started_at`, `finished_at`, `updated_at`)

Not found (`404`):
```json
{"detail":"Job not found"}
```

### GET `/jobs?status=&limit=`
Example request:
```bash
curl -s "http://127.0.0.1:18080/jobs?status=QUEUED&limit=10" \
  -H "X-Tenant-Id: team_alpha"
```
Success response (`200`): JSON array of `JobResponse` objects.

Validation failure (`422`) example (limit outside range):
```json
{"detail":[{"loc":["query","limit"],"msg":"...","type":"..."}]}
```

### POST `/jobs/{job_id}/cancel`
Example request:
```bash
curl -s -X POST http://127.0.0.1:18080/jobs/<job_id>/cancel \
  -H "X-Tenant-Id: team_alpha"
```
Success response (`200`):
```json
{"job_id":"<uuid>","status":"CANCELED"}
```

Failure responses:
- Not found (`404`):
```json
{"detail":"Job not found"}
```
- Conflict for non-queued jobs (`409`):
```json
{"detail":"Only QUEUED jobs can be canceled in M3.2"}
```

## Error Model

Current canonical error envelope (FastAPI default):
- Manual API errors use:
  - `{"detail":"<message>"}`
- Validation/parsing errors use:
  - `{"detail":[...validation entries...]}` with HTTP `422`.

Common failure mappings:
- Missing `X-Tenant-Id` on tenant-scoped endpoints -> `400`
- Invalid `X-Tenant-Id` format -> `400`
- Invalid request body/schema -> `422`
- Job not found (`GET /jobs/{id}`, `POST /jobs/{id}/cancel`) -> `404`
- Idempotency conflict -> `409`
- Submit throttled by per-tenant rate limit -> `429` (`Retry-After` header present)
- Submit rejected by admission cap -> `400`
- Cross-tenant read/cancel denial -> `404` (resource hiding policy)

## Observability Hooks
- API logs include correlation fields such as `job_id`, `status`, `attempts`, and idempotency conflict markers.
- Submit path persists optional metadata (`submitted_by`, `request_id`) and client host (`created_from_ip`) when available.
- Metrics endpoint (`/metrics`) exposes `job_system_*` metrics from shared metrics module.
- No explicit request-id middleware is implemented in current API path.

## Links
- Job lifecycle contract: [job-lifecycle.md](/mnt/d/Work/Code/Kubernetes/k8s-distributed-job-system/docs/contracts/job-lifecycle.md)
- Phase 4 plan: [phase4.md](/mnt/d/Work/Code/Kubernetes/k8s-distributed-job-system/docs/plans/phase4.md)
- P0.3 evidence pack: [docs/evidence/phase0/p0.3/](/mnt/d/Work/Code/Kubernetes/k8s-distributed-job-system/docs/evidence/phase0/p0.3)
