# k8s-distributed-job-system

Distributed systems learning repo for Kubernetes scheduling, pressure behavior, and model-serving operations.

## Repository Layout

- Baseline web manifests:
  - `k8s/deployment-web.yaml`
  - `k8s/service-web-svc.yaml`
- Scheduling experiments:
  - `k8s/experiments/scheduling/*`
- Pressure / QoS / eviction experiments:
  - `k8s/experiments/pressure/*`
- Model serving stack:
  - `k8s/model-serving/*`
- Evidence and reflections:
  - `docs/reflection.md`
  - `docs/evidence/*`
- Architecture docs:
  - `docs/architecture/system-overview.md`
  - `docs/architecture/component-boundaries.md`
  - `docs/contracts/job-lifecycle.md`
  - `docs/contracts/api.md`
  - `docs/contracts/db-schema.md`
- Operations docs:
  - `docs/operations/local-dev.md`
  - `docs/operations/observability.md`
  - `docs/operations/failure-modes.md`
  - `docs/operations/scaling-and-ha.md`

## Quickstart A: Model Serving (Phase 2)

Prerequisites:

- `kind`
- `kubectl`
- `docker`
- existing local cluster name: `ai-infra-lab`

Build and load image:

```bash
docker build -t fastapi-model-server:0.1.1 .
kind load docker-image fastapi-model-server:0.1.1 --name ai-infra-lab
```

Apply serving resources:

```bash
kubectl apply -f k8s/model-serving/model-server-deployment.yaml
kubectl apply -f k8s/model-serving/model-server-service.yaml
kubectl apply -f k8s/model-serving/model-server-ingress.yaml
kubectl apply -f k8s/model-serving/model-server-hpa.yaml
```

Force HPA scale-up:

```bash
kubectl apply -f k8s/model-serving/model-server-loadgen-job.yaml
kubectl get hpa model-server-hpa -w
```

Verify service + ingress:

```bash
kubectl run curl-svc --rm -i --restart=Never --image=curlimages/curl:8.12.1 --command -- sh -c "curl -s http://model-server-svc.default.svc.cluster.local/healthz"
kubectl run curl-ing --rm -i --restart=Never --image=curlimages/curl:8.12.1 --command -- sh -c "curl -s -H 'Host: model.local' http://ingress-nginx-controller.ingress-nginx.svc.cluster.local/healthz"
```

Observe HPA up/down:

```bash
kubectl get hpa model-server-hpa -o wide
kubectl describe hpa model-server-hpa
kubectl get deploy model-server -o wide
kubectl get pods -l app=model-server -o wide
```

## Success Criteria

- Model server responds on `/healthz` through service and ingress.
- HPA scales up under load (`2 -> 4 -> 6`).
- HPA scales down after load completion (returns to min replicas).
- Evidence is captured under `docs/evidence/` and summarized in `docs/reflection.md`.

## Quickstart B: Distributed Job System (Phase 3)

This section is the shortest end-to-end path for reviewers.

### Prerequisites

- `kind`, `kubectl`, `docker`
- Kind cluster name: `ai-infra-lab`

### 1) Build and load images into Kind

```bash
docker build -f Dockerfile.api -t job-system-api:0.1.0 .
docker build -f Dockerfile.scheduler -t job-system-scheduler:0.1.0 .

kind load docker-image job-system-api:0.1.0 --name ai-infra-lab
kind load docker-image job-system-scheduler:0.1.0 --name ai-infra-lab
```

### 2) Deploy Postgres + API + Scheduler

```bash
kubectl apply -f k8s/job-system/postgres.yaml
kubectl apply -f k8s/job-system/api-deployment.yaml
kubectl apply -f k8s/job-system/api-service.yaml
kubectl apply -f k8s/job-system/scheduler-serviceaccount.yaml
kubectl apply -f k8s/job-system/scheduler-role.yaml
kubectl apply -f k8s/job-system/scheduler-rolebinding.yaml
kubectl apply -f k8s/job-system/scheduler-deployment.yaml

kubectl rollout status deployment/job-system-postgres --timeout=180s
kubectl rollout status deployment/job-system-api --timeout=180s
kubectl rollout status deployment/job-system-scheduler --timeout=180s
```

### 3) Apply DB migrations

```bash
DB_POD=$(kubectl get pods -l app=job-system-postgres -o jsonpath='{.items[0].metadata.name}')
kubectl cp db/migrations/001_create_jobs.sql default/$DB_POD:/tmp/001_create_jobs.sql
kubectl cp db/migrations/002_m3_4_reliability.sql default/$DB_POD:/tmp/002_m3_4_reliability.sql
kubectl exec $DB_POD -- psql -U jobs -d jobs -f /tmp/001_create_jobs.sql
kubectl exec $DB_POD -- psql -U jobs -d jobs -f /tmp/002_m3_4_reliability.sql
```

### 4) Submit jobs through API

Start port-forward in one terminal:

```bash
kubectl port-forward svc/job-system-api 18080:80
```

In another terminal, submit a success job:

```bash
curl -s -X POST http://127.0.0.1:18080/jobs \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-success-1" \
  -d '{"image":"busybox:1.36","command":["sh","-c"],"args":["echo success; sleep 5; exit 0"],"queue":"default"}'
```

Submit a failing job with retries:

```bash
curl -s -X POST http://127.0.0.1:18080/jobs \
  -H "Content-Type: application/json" \
  -d '{"image":"busybox:1.36","command":["sh","-c"],"args":["echo fail; exit 1"],"queue":"default","max_retries":2,"backoff_seconds":3}'
```

### 5) Verify control-plane behavior

```bash
kubectl get jobs -l job-system/managed-by=scheduler -o wide
curl -s http://127.0.0.1:18080/jobs/<job_id>
```

Expected:
- `QUEUED -> RUNNING -> SUCCEEDED/FAILED` transitions in API response.
- Kubernetes Jobs created with labels:
  - `job-system/job-id`
  - `job-system/attempt`

Scheduler tenant quota knob:
- `TENANT_MAX_RUNNING` (default `2`) controls max concurrently running jobs per tenant.
- Configured in [scheduler-deployment.yaml](/mnt/d/Work/Code/Kubernetes/k8s-distributed-job-system/k8s/job-system/scheduler-deployment.yaml).

### 6) Verify metrics and logs

API metrics:

```bash
curl -s http://127.0.0.1:18080/metrics | grep job_system_
```

Scheduler metrics:

```bash
SCHED_POD=$(kubectl get pods -l app=job-system-scheduler -o jsonpath='{.items[0].metadata.name}')
kubectl port-forward pod/$SCHED_POD 19000:9000
curl -s http://127.0.0.1:19000/metrics | grep job_system_
```

Correlated logs:

```bash
kubectl logs deployment/job-system-api --tail=200
kubectl logs deployment/job-system-scheduler --tail=200
```

Expected: log lines contain `job_id=...` for submit, dispatch, retries, and terminal transitions.

## Known Limitations

- Postgres in `k8s/job-system/postgres.yaml` is ephemeral (Deployment, no PVC).
- Scheduler runs as a single replica (no leader election yet).
- Cancel endpoint currently supports `QUEUED` jobs only.
- Metrics counters are synchronized from DB totals; semantics depend on retained DB history.

## Phase 2 Completion Evidence

- Assessment narrative:
  - `docs/reflection.md` (section `12) HPA Scale-Up/Down Assessment (Load Generator)`)
- Baseline and final snapshots:
  - `docs/evidence/46-hpa-before-load.txt`
  - `docs/evidence/50-hpa-after-load.txt`
  - `docs/evidence/51-deploy-after-load.txt`
  - `docs/evidence/52-pods-after-load.txt`
- Timeline and event proof:
  - `docs/evidence/49-hpa-timeline-1.txt` ... `docs/evidence/49-hpa-timeline-56.txt`
  - `docs/evidence/54-hpa-scale-timeline.md`
  - `docs/evidence/53-events-hpa-updown-last-250.txt`
  - `docs/evidence/55-hpa-describe-final.txt`

## Phase 3 Evidence Packs

- Milestone journal:
  - `docs/reflection.md` (sections `13` through `17`)
- Evidence folders:
  - `docs/evidence/phase3/m3.1/`
  - `docs/evidence/phase3/m3.2/`
  - `docs/evidence/phase3/m3.3/`
  - `docs/evidence/phase3/m3.4/`
  - `docs/evidence/phase3/m3.5/`
