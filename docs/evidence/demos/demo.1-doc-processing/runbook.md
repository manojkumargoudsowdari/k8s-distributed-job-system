# DEMOS DEMO.1-DOC-PROCESSING Runbook

## Goal
Run a deterministic document-processing workload on top of the existing job platform (no core platform changes) and capture tenant isolation, fairness/quota signals, and result aggregation evidence.

## Prerequisites
- kind cluster: `ai-infra-lab`
- Running platform stack (Postgres, API, scheduler) from `k8s/job-system/*`
- Migrations applied from `db/migrations/*.sql`
- `docker`, `kubectl`, `curl`, and Python available

## One-command demo
```bash
bash scripts/demo_document_processing.sh
```

## Expected outputs
- `outputs/02-image-build-and-load.txt`: image build/load and deployment env knobs
- `outputs/03-job-submissions.txt`: tenant-a (6) + tenant-b (3) submission responses
- `outputs/04-results-aggregated.jsonl`: sorted worker JSON outputs by `doc_id`
- `outputs/05-fairness-and-quota-signals.txt`: scheduler log + metrics excerpts
- `outputs/06-rate-limit-optional.txt`: optional burst/429 probe

## What this proves
- Platform executes a useful workload image without platform logic changes.
- Multi-tenant behavior remains observable while running the workload.
- Worker output can be collected from Kubernetes pod logs and deterministically aggregated.
