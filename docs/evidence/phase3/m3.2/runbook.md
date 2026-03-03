# M3.2 Runbook - Job API + Idempotency

## Goal

Prove M3.2 behavior:

- API deploys and is reachable
- submit returns `job_id`
- repeated submit with same `Idempotency-Key` and same body returns same `job_id`
- get/list endpoints return expected data
- row is persisted in Postgres

## Prerequisites

- Running Kind cluster `ai-infra-lab`
- `kubectl` context set to that cluster
- Docker running locally

## Steps

1. Build API image from `Dockerfile.api`.
2. Import image into Kind node container runtime.
3. Deploy Postgres and API manifests from `k8s/job-system/`.
4. Apply `db/migrations/001_create_jobs.sql` inside the Postgres pod.
5. Port-forward API service and issue HTTP requests for health/submit/get/list.
6. Verify row in Postgres for submitted `job_id`.
7. Save outputs under `docs/evidence/phase3/m3.2/outputs/`.

## Expected Results

- API pod/service and Postgres pod/service are `Running`.
- `GET /healthz` returns `{"status":"ok"}`.
- First `POST /jobs` returns `201` with `job_id`.
- Repeated `POST /jobs` with same idempotency key/body returns same `job_id`.
- `GET /jobs/{job_id}` returns the persisted job in `QUEUED` status.
- `GET /jobs?status=QUEUED` includes that job.
- SQL verification returns one row matching `job_id` and idempotency key.

## Evidence Files

- `outputs/01-kubectl-get-all.txt`
- `outputs/02-api-health.txt`
- `outputs/03-submit-job-1.txt`
- `outputs/04-submit-idempotent-repeat.txt`
- `outputs/05-get-job.txt`
- `outputs/06-list-jobs-status.txt`
- `outputs/07-db-row-verification.txt`
