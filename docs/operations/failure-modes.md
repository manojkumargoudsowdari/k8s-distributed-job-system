# Failure Modes

| Failure Mode | Symptom | Detection Signal | Mitigation / Recovery |
|---|---|---|---|
| DB connection failure | API submit/get/list errors; scheduler stops progressing | API/scheduler logs with DB/connection errors; queue/running metrics stop changing | Restore Postgres availability, verify `DATABASE_URL`, restart affected deployment if needed |
| Scheduler crash/restart | Temporary dispatch/reconcile pause | Scheduler pod restart count/events; gap in `job_running` logs | Kubernetes restarts pod; scheduler reconcile loop resumes from DB state |
| Kubernetes Job creation failure | Job remains unexecuted; terminal failure may be recorded | Scheduler logs `k8s_job_create_failed`; failed transition logs | Fix RBAC/image/spec issue and resubmit; inspect scheduler role and k8s events |
| Stuck `QUEUED` jobs | Jobs do not move to `RUNNING` | API list shows long-lived `QUEUED`; scheduler logs show quota/backoff gating or no dispatch | Check tenant quota (`TENANT_MAX_RUNNING`), retry gate (`next_retry_at`), scheduler health, DB readiness |
| Repeated retries/backoff | Same job cycles `RUNNING -> QUEUED` before terminal | Logs show `job_requeued_for_retry`; retry counter and attempts increase | Confirm failure root cause, adjust `max_retries`/`backoff_seconds`, inspect container command/image |
| Tenant quota blocking (expected) | Additional jobs for same tenant remain `QUEUED` while limit reached | Scheduler logs `dispatch_skipped_tenant_quota`; running count for tenant at limit | Wait for running jobs to complete or adjust `TENANT_MAX_RUNNING` for workload profile |
