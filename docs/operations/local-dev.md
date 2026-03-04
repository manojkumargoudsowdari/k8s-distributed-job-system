# Local Dev

## Prerequisites
- `kind`
- `kubectl`
- `docker`
- Python `3.12` (aligned with CI and Dockerfiles)

## Quick Start (API + Scheduler + DB)

1. Build images:
```bash
docker build -f Dockerfile.api -t job-system-api:0.1.0 .
docker build -f Dockerfile.scheduler -t job-system-scheduler:0.1.0 .
```

2. Load images into Kind cluster (`ai-infra-lab`):
```bash
kind load docker-image job-system-api:0.1.0 --name ai-infra-lab
kind load docker-image job-system-scheduler:0.1.0 --name ai-infra-lab
```

3. Deploy DB/API/scheduler:
```bash
kubectl apply -f k8s/job-system/postgres.yaml
kubectl apply -f k8s/job-system/api-deployment.yaml
kubectl apply -f k8s/job-system/api-service.yaml
kubectl apply -f k8s/job-system/scheduler-serviceaccount.yaml
kubectl apply -f k8s/job-system/scheduler-role.yaml
kubectl apply -f k8s/job-system/scheduler-rolebinding.yaml
kubectl apply -f k8s/job-system/scheduler-deployment.yaml
```

4. Wait for rollouts:
```bash
kubectl rollout status deployment/job-system-postgres --timeout=180s
kubectl rollout status deployment/job-system-api --timeout=180s
kubectl rollout status deployment/job-system-scheduler --timeout=180s
```

5. Apply migrations:
```bash
DB_POD=$(kubectl get pods -l app=job-system-postgres -o jsonpath='{.items[0].metadata.name}')
kubectl cp db/migrations/001_create_jobs.sql default/$DB_POD:/tmp/001_create_jobs.sql
kubectl cp db/migrations/002_m3_4_reliability.sql default/$DB_POD:/tmp/002_m3_4_reliability.sql
kubectl cp db/migrations/003_m4_1_tenant_identity.sql default/$DB_POD:/tmp/003_m4_1_tenant_identity.sql
kubectl exec $DB_POD -- psql -U jobs -d jobs -f /tmp/001_create_jobs.sql
kubectl exec $DB_POD -- psql -U jobs -d jobs -f /tmp/002_m3_4_reliability.sql
kubectl exec $DB_POD -- psql -U jobs -d jobs -f /tmp/003_m4_1_tenant_identity.sql
```

## Lint and Tests
- Same commands as CI:
```bash
python -m ruff check .
python -m unittest discover -s tests -p "test_*.py"
```

## Runtime Validation
1. Port-forward API:
```bash
kubectl port-forward svc/job-system-api 18080:80
```

2. Health endpoint:
```bash
curl -s http://127.0.0.1:18080/healthz
```

3. API metrics endpoint:
```bash
curl -s http://127.0.0.1:18080/metrics | grep job_system_
```

4. Submit sample job with tenant header:
```bash
curl -s -X POST http://127.0.0.1:18080/jobs \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: team_alpha" \
  -H "Idempotency-Key: local-dev-001" \
  -d '{"image":"busybox:1.36","command":["sh","-c"],"args":["echo ok; sleep 3; exit 0"],"queue":"default"}'
```

5. Verify lifecycle:
```bash
curl -s http://127.0.0.1:18080/jobs/<job_id>
kubectl get jobs -l job-system/managed-by=scheduler -o wide
```

## Logs and What to Check
- API logs:
```bash
kubectl logs deployment/job-system-api --tail=200
```
- Scheduler logs:
```bash
kubectl logs deployment/job-system-scheduler --tail=200
```

Look for:
- submit path (`submit_created`, `submit_idempotent_hit`)
- scheduler transitions (`job_running`, `job_succeeded`, `job_failed`, `job_requeued_for_retry`)
- failure/recovery signals (`k8s_job_create_failed`, `missing_k8s_job_failed`, `job_timeout_failed`)
