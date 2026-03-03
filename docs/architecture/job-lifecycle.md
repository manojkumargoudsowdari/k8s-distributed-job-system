# Job Lifecycle (M3.1)

## States

- `QUEUED`
- `RUNNING`
- `SUCCEEDED`
- `FAILED`
- `CANCELED`

## Allowed transitions

- `QUEUED -> RUNNING`
- `QUEUED -> CANCELED`
- `RUNNING -> SUCCEEDED`
- `RUNNING -> FAILED`
- `RUNNING -> CANCELED`

Terminal states: `SUCCEEDED`, `FAILED`, `CANCELED`.

## Attempt model

- `jobs.attempts` tracks current total attempts.
- `job_attempts` stores per-attempt records (`attempt_number`, start/end, exit/error).

## Ownership

- Postgres is source of truth for job state.
- Scheduler/executor reconciles desired/observed execution and updates DB.

## Timestamps

- `created_at`, `queued_at`, `started_at`, `finished_at`, `updated_at` on `jobs`.
- `started_at`, `finished_at` on `job_attempts`.

## Cancellation model

- API can set `desired_status=CANCELED`.
- Reconciler enforces cancellation and sets terminal `status=CANCELED`.
