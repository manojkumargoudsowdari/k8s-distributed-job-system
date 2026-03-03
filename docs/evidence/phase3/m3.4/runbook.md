# M3.4 Runbook - Reliability Layer (Retry/Backoff/Timeout/Recovery)

## Goal

Validate reliability behaviors on top of M3.3 scheduler dispatch:

- Retry policy using `max_retries` and attempt tracking.
- Exponential backoff gate via `next_retry_at`.
- Timeout enforcement for long-running jobs.
- Recovery from scheduler pod restart.

## Scope

- No metrics (M3.5).
- No Redis/external queue.
- Single scheduler deployment.

## Steps

1. Build and load latest API + scheduler images into Kind.
2. Apply M3.4 migration (`002_m3_4_reliability.sql`).
3. Deploy/restart API + scheduler and apply updated RBAC.
4. Submit a flaky failing job (`max_retries=3`, `backoff_seconds=5`).
5. Poll API to capture status and attempts over time.
6. Capture scheduler logs that show retry requeue.
7. Submit timeout job (`timeout_seconds=10`, long sleep), confirm `last_error=timeout`.
8. Kill scheduler pod during active work, confirm processing continues after restart.

## Expected Outcomes

- Flaky job:
  - transitions across attempts and ends `FAILED` after retry budget exhausted.
  - `next_retry_at` increases between retries.
- Timeout job:
  - scheduler marks it `FAILED` with `last_error=timeout`.
  - backing Kubernetes Job/Pod is terminated.
- Restart proof:
  - deleting scheduler pod does not lose job processing.
  - in-flight job still reaches terminal state.

## Evidence Files

- `01-submit-flaky-job.txt`
- `02-retry-attempts-api.txt`
- `03-scheduler-logs-retry.txt`
- `04-backoff-timeline.txt`
- `05-submit-timeout-job.txt`
- `06-k8s-job-terminated-timeout.txt`
- `07-api-job-failed-timeout.txt`
- `08-restart-scheduler-proof.txt`
