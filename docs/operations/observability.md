# Observability

## Metrics Endpoints

## API metrics
- Path: `GET /metrics`
- Local access (port-forward):
```bash
kubectl port-forward svc/job-system-api 18080:80
curl -s http://127.0.0.1:18080/metrics | grep job_system_
```

## Scheduler metrics
- Exposed by scheduler process on `SCHEDULER_METRICS_PORT` (default `9000`).
- Local access:
```bash
SCHED_POD=$(kubectl get pods -l app=job-system-scheduler -o jsonpath='{.items[0].metadata.name}')
kubectl port-forward pod/$SCHED_POD 19000:9000
curl -s http://127.0.0.1:19000/metrics | grep job_system_
```

## Key Metrics (as implemented)
- `job_system_jobs_queued` (gauge)
- `job_system_jobs_running` (gauge)
- `job_system_jobs_queued_by_tenant_bucket{tenant_bucket="0..f"}` (gauge)
- `job_system_jobs_running_by_tenant_bucket{tenant_bucket="0..f"}` (gauge)
- `job_system_job_success_total` (counter)
- `job_system_job_fail_total` (counter)
- `job_system_job_retries_total` (counter)
- `job_system_job_latency_seconds` (histogram)
- `job_system_scheduler_dispatch_decisions_total{decision=...}` (counter)
- `job_system_scheduler_dispatch_decisions_by_tenant_bucket_total{decision=...,tenant_bucket="0..f"}` (counter)
- `job_system_scheduler_quota_blocks_total` (counter)
- `job_system_scheduler_quota_blocks_by_tenant_bucket_total{tenant_bucket="0..f"}` (counter)
- `job_system_api_submit_rate_limited_total` (counter)
- `job_system_api_submit_rate_limited_by_tenant_bucket_total{tenant_bucket="0..f"}` (counter)

Cardinality safeguard:
- Tenant metrics use hashed tenant buckets (`0..f`) instead of raw `tenant_id` labels.

## Logging Signals

Important log fields/markers:
- `job_id`
- `tenant_id`
- `status` / attempt transitions

Examples:
- API:
  - `submit_created tenant_id=... job_id=... status=...`
  - `submit_rate_limited tenant_id=... retry_after=...`
  - `submit_idempotent_hit job_id=... status=...`
  - `get_job job_id=... status=... attempts=...`
- Scheduler:
  - `job_running tenant_id=... job_id=... attempt=...`
  - `dispatch_skipped_tenant_quota tenant_id=... running=... limit=... job_id=...`
  - `dispatch_no_candidates`
  - `job_succeeded job_id=...`
  - `job_requeued_for_retry job_id=... next_retry_at=...`
  - `job_failed job_id=... error=...`
  - `job_timeout_failed job_id=...`

## Recommended Alerts / SLO Ideas (Docs-only)
- Queue saturation:
  - Alert when `job_system_jobs_queued` remains above threshold for sustained window.
- Failure rate:
  - Alert on slope increase in `job_system_job_fail_total`.
- Retry storm:
  - Alert on rapid increase of `job_system_job_retries_total`.
- High latency:
  - Use `job_system_job_latency_seconds` high-percentile thresholds.
- Scheduler health:
  - Alert if scheduler logs stop emitting transition events while queued jobs continue growing.
