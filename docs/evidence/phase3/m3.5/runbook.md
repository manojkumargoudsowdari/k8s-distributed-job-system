# M3.5 Observability Runbook

## Goal
Validate Prometheus metrics exposure and structured log correlation for the distributed job system.

## Preconditions
- Kind cluster `ai-infra-lab` is running.
- `job-system-postgres`, `job-system-api`, and `job-system-scheduler` deployments are healthy.
- M3.4 migrations are already applied.

## Steps
1. Capture baseline metrics from scheduler.
2. Submit 20 jobs (10 success, 10 fail-with-retry).
3. Capture metrics during active processing.
4. Wait for queue drain and capture metrics after completion.
5. Capture API and scheduler logs showing `job_id` correlation.

## Success Criteria
- `/metrics` emits Prometheus text exposition format.
- Required metrics exist:
  - `job_system_jobs_queued`
  - `job_system_jobs_running`
  - `job_system_job_success_total`
  - `job_system_job_fail_total`
  - `job_system_job_retries_total`
  - `job_system_job_latency_seconds`
- During load, queued/running increase.
- After drain, queued/running return to zero.
- Logs include lifecycle lines with `job_id=` for API and scheduler.

## Evidence Files
- `outputs/01-metrics-baseline.txt`
- `outputs/02-submit-20-jobs.txt`
- `outputs/03-metrics-during-load.txt`
- `outputs/04-metrics-after-drain.txt`
- `outputs/05-logs-correlation.txt`
