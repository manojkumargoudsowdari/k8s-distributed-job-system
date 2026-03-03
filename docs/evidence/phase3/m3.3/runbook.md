# M3.3 Runbook - Scheduler Dispatch + Completion Tracking

## Goal

Demonstrate end-to-end scheduler behavior:

- API creates `QUEUED` jobs.
- Scheduler creates Kubernetes Jobs from queued rows.
- Job status transitions are persisted:
  - `QUEUED -> RUNNING -> SUCCEEDED`
  - `QUEUED -> RUNNING -> FAILED`
- API `GET /jobs/{id}` reflects transitions correctly.

## Prerequisites

- Kind cluster `ai-infra-lab` is running.
- Docker Desktop running.
- `kubectl` points to the Kind cluster.
- Repo root: `k8s-distributed-job-system`.

## Steps

1. Build and import `job-system-scheduler:0.1.0` image into Kind.
2. Apply Postgres/API manifests and scheduler RBAC + deployment.
3. Apply migration and reset DB tables for deterministic evidence.
4. Submit a success job using API and capture:
   - Kubernetes Job creation
   - API `RUNNING`
   - API `SUCCEEDED`
   - Pod logs
5. Submit an intentional failing job and capture:
   - API submit output
   - API `FAILED`
6. Verify DB rows and timestamps for transitions.

## Expected Results

- Success path:
  - K8s Job created and traceable via label `job-system/job-id=<job_id>`.
  - API transitions from `RUNNING` to `SUCCEEDED`.
- Failure path:
  - K8s Job created and then failed.
  - API returns `FAILED` with a failure reason.
- DB shows both jobs with non-null `started_at` and `finished_at`.

## Evidence Files

- `outputs/01-submit-job-succeeds.txt`
- `outputs/02-kubectl-get-jobs.txt`
- `outputs/03-kubectl-describe-job.txt`
- `outputs/04-kubectl-logs-job-pod.txt`
- `outputs/05-api-get-job-running.txt`
- `outputs/06-api-get-job-succeeded.txt`
- `outputs/07-db-state-transitions.txt`
- `outputs/08-submit-job-fails.txt`
- `outputs/09-api-get-job-failed.txt`
