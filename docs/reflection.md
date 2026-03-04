# Reflection Log - Week 1 Evidence

Date: 2026-03-03  
Cluster: `ai-infra-lab`  
Context: `kind-ai-infra-lab`

## 1) Manifest Validation

Commands run:

```bash
kubectl apply -f k8s/deployment-web.yaml
kubectl apply -f k8s/service-web-svc.yaml
kubectl get deploy,rs,pods,svc -o wide
kubectl describe deploy web
kubectl describe svc web-svc
kubectl get events --sort-by=.lastTimestamp | tail -n 30
```

Output (`kubectl get deploy,rs,pods,svc -o wide`):

```text
NAME                  READY   UP-TO-DATE   AVAILABLE   AGE   CONTAINERS   IMAGES         SELECTOR
deployment.apps/web   3/3     3            3           66s   nginx        nginx:latest   app=web

NAME                             DESIRED   CURRENT   READY   AGE   CONTAINERS   IMAGES         SELECTOR
replicaset.apps/web-6c79984869   0         0         0       66s   nginx        nginx:latest   app=web,pod-template-hash=6c79984869
replicaset.apps/web-7f45bc5875   3         3         3       32s   nginx        nginx:latest   app=web,pod-template-hash=7f45bc5875
replicaset.apps/web-7f8868fb57   0         0         0       48s   nginx        nginx:latest   app=web,pod-template-hash=7f8868fb57

NAME                       READY   STATUS    RESTARTS   AGE   IP            NODE                         NOMINATED NODE   READINESS GATES
pod/web-7f45bc5875-bhrlm   1/1     Running   0          27s   10.244.0.10   ai-infra-lab-control-plane   <none>           <none>
pod/web-7f45bc5875-clr5w   1/1     Running   0          29s   10.244.0.9    ai-infra-lab-control-plane   <none>           <none>
pod/web-7f45bc5875-s5xl7   1/1     Running   0          32s   10.244.0.8    ai-infra-lab-control-plane   <none>           <none>

NAME                 TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)        AGE   SELECTOR
service/kubernetes   ClusterIP   10.96.0.1      <none>        443/TCP        93s   <none>
service/web-svc      NodePort    10.96.180.80   <none>        80:32331/TCP   66s   app=web
```

Output (`kubectl describe svc web-svc`):

```text
Name:                     web-svc
Namespace:                default
Selector:                 app=web
Type:                     NodePort
IP:                       10.96.180.80
Port:                     <unset>  80/TCP
TargetPort:               80/TCP
NodePort:                 <unset>  32331/TCP
Endpoints:                10.244.0.8:80,10.244.0.9:80,10.244.0.10:80
Events:                   <none>
```

## 2) Intentional Scheduler Break

Manifest change:

```yaml
resources:
  requests:
    cpu: "10"
    memory: "20Gi"
  limits:
    cpu: "10"
    memory: "20Gi"
```

Commands run:

```bash
kubectl apply -f k8s/deployment-web.yaml
kubectl get pods -o wide
kubectl describe pod web-7f8868fb57-4766z
```

Output (`kubectl get pods -o wide` excerpt):

```text
NAME                   READY   STATUS    RESTARTS   AGE   IP       NODE     NOMINATED NODE   READINESS GATES
web-7f8868fb57-4766z   0/1     Pending   0          3s    <none>   <none>   <none>           <none>
```

Required capture (only pod status + events):

```text
Status:           Pending
```

```text
Events:
  Type     Reason            Age   From               Message
  ----     ------            ----  ----               -------
  Warning  FailedScheduling  6s    default-scheduler  0/1 nodes are available: 1 Insufficient memory. preemption: 0/1 nodes are available: 1 No preemption victims found for incoming pod.
```

Fix applied:

```yaml
resources:
  requests:
    cpu: "100m"
    memory: "128Mi"
  limits:
    cpu: "500m"
    memory: "512Mi"
```

## 3) Scaling Proof

Commands run:

```bash
kubectl scale deployment web --replicas=3
kubectl get pods -o wide
kubectl describe deploy web
```

Output (`kubectl get pods -o wide`):

```text
NAME                   READY   STATUS    RESTARTS   AGE   IP            NODE                         NOMINATED NODE   READINESS GATES
web-7f45bc5875-bhrlm   1/1     Running   0          28s   10.244.0.10   ai-infra-lab-control-plane   <none>           <none>
web-7f45bc5875-clr5w   1/1     Running   0          30s   10.244.0.9    ai-infra-lab-control-plane   <none>           <none>
web-7f45bc5875-s5xl7   1/1     Running   0          33s   10.244.0.8    ai-infra-lab-control-plane   <none>           <none>
```

Output (`kubectl describe deploy web` excerpt):

```text
Replicas:               3 desired | 3 updated | 3 total | 3 available | 0 unavailable
Conditions:
  Type           Status  Reason
  ----           ------  ------
  Available      True    MinimumReplicasAvailable
  Progressing    True    NewReplicaSetAvailable
```

## 4) Scheduling Analysis (Deep Dive)

Why the scheduler rejected the pod:

- The pod was `Pending` because its **requested** memory (`20Gi`) could not fit on any node.
- Scheduler event was explicit: `0/1 nodes are available: 1 Insufficient memory`.
- Kubernetes scheduler performs bin-packing against node allocatable resources and does not do partial placement.

What part of the spec caused it:

- `spec.template.spec.containers[].resources.requests` was set to:
  - `cpu: "10"`
  - `memory: "20Gi"`
- Those request values are the admission criteria for scheduling.

Node allocatable vs total node capacity:

- `Capacity` is raw hardware/VM capacity reported by the node.
- `Allocatable` is what pods can actually consume after reserving resources for:
  - kubelet/system daemons
  - eviction thresholds and kube-reserved/system-reserved overhead
- Scheduling decisions use **allocatable**, not total capacity.

Why limits did not drive scheduling:

- Scheduler checks `requests` for placement.
- `limits` are runtime cgroup ceilings enforced by kubelet/container runtime **after** a pod is scheduled.
- So:
  - Too-high request -> pod stays `Pending` (`FailedScheduling`).
  - Reasonable request but too-low limit under load -> pod schedules, then can hit `OOMKilled`.

YARN mental mapping:

- This is analogous to YARN not launching a container when requested memory does not fit queue/node headroom.
- Difference: Kubernetes evaluates at pod/container granularity with explicit request/limit separation.

## 5) Why Multiple ReplicaSets Appeared

- Deployment controller creates a new ReplicaSet whenever the pod template changes.
- In this lab, template changed twice:
  - Default/no resources -> high requests (`10 CPU`, `20Gi`)
  - High requests -> normalized schedulable values (`100m/128Mi`, `500m/512Mi`)
- Each unique template hash produced a different ReplicaSet.
- RollingUpdate strategy (`maxUnavailable 25%`, `maxSurge 25%`) scaled new ReplicaSets up while scaling old ReplicaSets down, which is why multiple ReplicaSets coexisted temporarily.

## 6) Runtime Enforcement Test (OOMKilled)

Test setup (same small request/limit, memory stress at runtime):

```yaml
image: polinux/stress
command: ["stress"]
args: ["--vm", "1", "--vm-bytes", "300M", "--vm-hang", "1"]
resources:
  requests:
    cpu: "100m"
    memory: "128Mi"
  limits:
    cpu: "500m"
    memory: "128Mi"
```

Observed behavior:

- Pod was successfully scheduled to node (`PodScheduled=True`).
- Container exceeded `128Mi` limit at runtime.
- Pod entered restart loop with `CrashLoopBackOff`.
- `kubectl describe pod` showed:

```text
Last State:     Terminated
  Reason:       OOMKilled
  Exit Code:    137
```

Key command evidence:

- `kubectl get pods -o wide` -> `CrashLoopBackOff`
- `kubectl describe pod <pod>` -> `Reason: OOMKilled`
- `kubectl logs <pod> --previous` -> stress process started and then terminated

Assessment answers:

1. Why did scheduling succeed?
- Requests were schedulable (`100m` CPU, `128Mi` memory) relative to node allocatable resources, so kube-scheduler placed the pod.

2. Why did runtime fail?
- Process tried to allocate `300M` while container memory limit was `128Mi`; runtime memory cgroup limit was exceeded, so container was killed.

3. What enforces memory limit?
- Linux kernel cgroup/OOM enforcement kills the process when memory limit is exceeded.
- Kubelet observes that termination, reports `OOMKilled`, and drives restart behavior per pod restart policy.

4. Difference between kube-scheduler and kubelet roles?
- kube-scheduler: placement decision (which node) based mainly on requests/constraints.
- kubelet: node-level execution and enforcement (start/restart containers, enforce limits, report status/events).

5. How is this different from YARN executor memory failure?
- Similarity: container/executor can start and then die due to memory overuse.
- Difference: Kubernetes separates scheduling (`requests`) and runtime cap (`limits`) explicitly per container; YARN typically reasons in container memory allocation plus executor/JVM overhead semantics.

Precision check:

- Who kills container over memory limit?
  - Precise answer: Linux kernel kills it via cgroup/OOM enforcement.
  - Operationally in Kubernetes: kubelet reports `OOMKilled` and restarts the container.

## 7) Scheduling Constraints Milestone (Taints/Tolerations)

Goal reproduced:

- `node(s) had untolerated taint {gpu: true}`

Steps and results:

1. Added taint:

```bash
kubectl taint nodes ai-infra-lab-control-plane gpu=true:NoSchedule
```

2. Created pod **without** toleration (`taint-test-no-toleration`):

- Status: `Pending`
- `PodScheduled=False`
- Event:

```text
Warning  FailedScheduling  ...  0/1 nodes are available: 1 node(s) had untolerated taint {gpu: true}.
```

3. Created pod **with** toleration (`taint-test`):

```yaml
tolerations:
  - key: "gpu"
    operator: "Equal"
    value: "true"
    effect: "NoSchedule"
```

- Status: `Running`
- `PodScheduled=True`
- Scheduler event confirms assignment to `ai-infra-lab-control-plane`.

## 8) Node Selection vs Affinity (Positive Placement)

Goal:

- Control placement by selecting eligible nodes (without taints).

Task A: Node label

```bash
kubectl label node ai-infra-lab-control-plane pool=default --overwrite
```

Task B: `nodeSelector` pod

- Pod spec used:

```yaml
nodeSelector:
  pool: default
```

- Result: pod scheduled onto `ai-infra-lab-control-plane`.
- Evidence: `13-node-selector-describe-pod.txt`

Task C: `nodeAffinity` pod (`requiredDuringSchedulingIgnoredDuringExecution`)

- Pod spec used:

```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: pool
              operator: In
              values: ["default"]
```

- Result: pod scheduled onto `ai-infra-lab-control-plane`.
- Evidence: `14-node-affinity-describe-pod.txt`

Assessment answers:

1. Difference: `nodeSelector` vs `nodeAffinity`
- `nodeSelector` is exact-match and simple (all specified labels must match).
- `nodeAffinity` is expressive (operators like `In`, `NotIn`, `Exists`; multiple terms; preferred vs required).

2. When to use taints/tolerations vs affinity/selector
- `nodeSelector`/`nodeAffinity`: positive placement (where pod is allowed/preferred to run).
- `taints`/`tolerations`: negative placement/repulsion (keep pods off nodes unless they explicitly tolerate).
- Common pattern: taint dedicated nodes (e.g., GPU), then add toleration + affinity/selector on intended workloads.

3. What happens if label is removed after scheduling (`IgnoredDuringExecution`)?
- Existing pod keeps running; it is not evicted just because node label changed.
- Constraint is enforced during scheduling, not continuously for already-running pod.
- Confirmed by removing label and observing pods remained running (`16-after-label-removal-pods-wide.txt`).

## 9) QoS Classes + Pressure Behavior

Goal:

- Prove `BestEffort`, `Burstable`, `Guaranteed`.
- Generate node memory pressure and observe behavior.

Pods created:

- `qos-best-effort` (no requests/limits)
- `qos-burstable` (requests < limits)
- `qos-guaranteed` (requests == limits for cpu+memory)

QoS evidence:

- `18-qos-best-effort-describe-pod.txt` -> `QoS Class: BestEffort`
- `19-qos-burstable-describe-pod.txt` -> `QoS Class: Burstable`
- `20-qos-guaranteed-describe-pod.txt` -> `QoS Class: Guaranteed`

Pressure generator:

- `qos-pressure-deploy` with multiple `stress` pods allocating large memory.

Observed result in this run:

- Node emitted repeated `SystemOOM` events (kernel OOM killer) during pressure.
- Pressure pods repeatedly entered `OOMKilled`/restart loops.
- QoS demo pods remained `Running`.
- Node condition snapshot still showed `MemoryPressure=False` at capture time.

Important interpretation:

- This run demonstrated runtime memory collapse via kernel OOM (`SystemOOM`) rather than kubelet eviction (`Evicted` reason).
- So this environment produced a clear pressure signal, but not a clean kubelet eviction-order trace in captured events.

Assessment answers:

1. How Kubernetes computes QoS class
- `Guaranteed`: every container has cpu+memory requests and limits, and each request equals limit.
- `Burstable`: at least one request/limit set, but not all equal across cpu+memory.
- `BestEffort`: no requests and no limits set for any container.

2. Eviction order under memory pressure
- Kubelet eviction policy generally targets lower QoS first:
  - `BestEffort` first,
  - then `Burstable` (especially those exceeding requests),
  - `Guaranteed` last.
- In this specific run, kernel `SystemOOM` occurred before a recorded kubelet `Evicted` sequence.

3. Why this matters for model serving vs batch training
- Model serving should typically be protected (often `Guaranteed` or tightly bounded `Burstable`) to reduce latency spikes and unexpected restarts.
- Batch training/experimental jobs can often tolerate preemption/eviction better and are usually placed with lower protection.
- Correct QoS choice is a reliability SLO decision, not just a resource syntax choice.

## 10) Focused Rerun: Clean Kubelet Eviction Evidence

Why rerun:

- Prior run hit `SystemOOM` before clean kubelet eviction signal.
- Recreated Kind cluster with aggressive kubelet eviction settings.

Cluster config used (`kind-evict.yaml`):

```yaml
evictionHard:
  memory.available: "1.5Gi"
  nodefs.available: "10%"
  imagefs.available: "10%"
evictionPressureTransitionPeriod: "30s"
```

Outcome:

- Success criteria met.
- Multiple pods reached `Status: Failed`, `Reason: Evicted`.
- Events include `MemoryPressure` and `EvictionThresholdMet`.

Direct evidence:

- `25-evict-rerun-get-pods-wide.txt`
- `26-evict-rerun-events-last-200.txt`
- `27-evict-rerun-describe-qos-best-effort.txt`
- `28-evict-rerun-describe-node.txt`
- `29-evict-rerun-describe-evicted-pod.txt`

Key lines observed:

- `Reason: Evicted`
- `The node had condition: [MemoryPressure]`
- `EvictionThresholdMet ... Attempting to reclaim memory`

Interpretation:

- This run captured kubelet-driven eviction (proactive reclaim under pressure), not just kernel OOM kills.
- It closes the reliability gap between "runtime OOM" and "policy-based eviction under node pressure."

## 11) ML Workload + Serving (Initial Phase)

Implemented:

- Simple FastAPI model server (`/healthz`, `/predict`) in `app/main.py`
- Containerized with `Dockerfile` and local image `fastapi-model-server:0.1.0`
- Kubernetes manifests:
  - Deployment: `k8s/model-serving/model-server-deployment.yaml`
  - Service: `k8s/model-serving/model-server-service.yaml`
  - Ingress: `k8s/model-serving/model-server-ingress.yaml`
  - HPA: `k8s/model-serving/model-server-hpa.yaml`

Platform components added:

- `ingress-nginx` (Kind provider manifest)
- `metrics-server` (patched for Kind kubelet TLS)

Validation:

- Deployment rolled out with 2 running replicas.
- Ingress routing works:
  - `Host: model.local` + `/healthz` returns `{"status":"ok"}`.
- CPU/memory metrics available via `kubectl top`.

Evidence:

- `31-model-serving-resources.txt`
- `32-model-serving-top-nodes.txt`
- `33-model-serving-top-pods.txt`
- `34-model-serving-describe-hpa.txt`
- `35-model-serving-ingress-healthz.txt`
- `36-post-cleanup-pods.txt`

## 12) HPA Scale-Up/Down Assessment (Load Generator)

Goal:

- Force HPA CPU target breach and capture both scale-up and scale-down evidence.

Changes:

- Added CPU burn endpoint in app:
  - `GET /burn?ms=<n>` in `app/main.py`
- Added load generator Job:
  - `k8s/model-serving/model-server-loadgen-job.yaml`
  - 8 parallel workers repeatedly call `/burn`.
- Updated deployment image to `fastapi-model-server:0.1.1`.

Observed scaling:

- Baseline started at `2` replicas.
- HPA scaled `model-server` from `2` -> `4` -> `6` replicas under load.
- HPA reached max replica bound (`maxReplicas: 6`) with `ScalingLimited=True`.
- After load completed and stabilization elapsed, HPA scaled back down to `2`.

Key evidence:

- Baseline + final snapshots:
  - `46-hpa-before-load.txt`
  - `50-hpa-after-load.txt`
  - `51-deploy-after-load.txt`
  - `52-pods-after-load.txt`
- Timeline snapshots:
  - `49-hpa-timeline-1.txt` ... `49-hpa-timeline-56.txt`
  - `54-hpa-scale-timeline.md`
- HPA events and conditions:
  - `55-hpa-describe-final.txt`
  - `53-events-hpa-updown-last-250.txt`
- Previous loadgen run evidence (still valid):
  - `38-hpa-describe-after-loadgen.txt`
  - `39-events-after-loadgen-last-200.txt`

Operational note:

- Job used `ttlSecondsAfterFinished: 120`, so completed Job/Pods were auto-removed.
- TTL cleanup evidence:
  - `41-loadgen-job-ttl-cleanup.txt`

## 13) Phase 3 M3.1 - Domain + Persistence

What changed:

- Added migration:
  - `db/migrations/001_create_jobs.sql`
- Added lifecycle architecture note:
  - `docs/architecture/job-lifecycle.md`
- Added minimal DB access layer:
  - `pkg/job_system/models.py`
  - `pkg/job_system/db.py`
  - `scripts/m3_1_db_smoke.py`
  - `requirements-phase3.txt`

What was proven:

- Postgres reachable and migration applied.
- `jobs` table exists with required columns and indexes.
- Insert/select works for sample job row.
- Status transitions can be recorded (`QUEUED -> RUNNING -> SUCCEEDED`).

Evidence:

- `docs/evidence/phase3/m3.1/01-psql-connection.txt`
- `docs/evidence/phase3/m3.1/02-migration-applied.txt`
- `docs/evidence/phase3/m3.1/03-schema-jobs-table.txt`
- `docs/evidence/phase3/m3.1/04-indexes.txt`
- `docs/evidence/phase3/m3.1/05-sample-insert-select.txt`
- `docs/evidence/phase3/m3.1/runbook.md`
- `docs/evidence/phase3/m3.1/commands.txt`

## 14) Phase 3 M3.2 - Job API + Idempotent Submit

What changed:

- Added API service:
  - `services/api/main.py`
  - `services/api/__init__.py`
  - `services/__init__.py`
- Added API image definition:
  - `Dockerfile.api`
  - `services/api/requirements.txt`
- Added M3.2 Kubernetes manifests:
  - `k8s/job-system/postgres.yaml`
  - `k8s/job-system/api-deployment.yaml`
  - `k8s/job-system/api-service.yaml`
- Extended M3.1 DB/model support for API contract:
  - `pkg/job_system/db.py` (idempotency lookup + backoff/timeout fields)
  - `pkg/job_system/models.py`
- Added minimal API tests:
  - `tests/test_m3_2_api.py`

What was proven:

- API and Postgres deployed in cluster and reachable.
- `POST /jobs` returns `job_id` and `QUEUED`.
- Re-submit with same `Idempotency-Key` and same body returns same `job_id`.
- `GET /jobs/{job_id}` returns full persisted job payload.
- `GET /jobs?status=QUEUED&limit=10` filters as expected.
- Postgres row verification confirms stored `idempotency_key`, `status`, and retry/backoff fields.
- `POST /jobs/{job_id}/cancel` is implemented for `QUEUED` jobs in M3.2 as an immediate DB status transition; controller-driven cancellation semantics are deferred to M3.3.

Evidence:

- `docs/evidence/phase3/m3.2/outputs/01-kubectl-get-all.txt`
- `docs/evidence/phase3/m3.2/outputs/02-api-health.txt`
- `docs/evidence/phase3/m3.2/outputs/03-submit-job-1.txt`
- `docs/evidence/phase3/m3.2/outputs/04-submit-idempotent-repeat.txt`
- `docs/evidence/phase3/m3.2/outputs/05-get-job.txt`
- `docs/evidence/phase3/m3.2/outputs/06-list-jobs-status.txt`
- `docs/evidence/phase3/m3.2/outputs/07-db-row-verification.txt`
- `docs/evidence/phase3/m3.2/runbook.md`
- `docs/evidence/phase3/m3.2/commands.txt`

## 15) Phase 3 M3.3 - Scheduler Dispatch + Completion Tracking

What changed:

- Added scheduler service:
  - `services/scheduler/main.py`
  - `services/scheduler/requirements.txt`
  - `services/scheduler/__init__.py`
- Added scheduler image definition:
  - `Dockerfile.scheduler`
- Added scheduler RBAC + deployment manifests:
  - `k8s/job-system/scheduler-serviceaccount.yaml`
  - `k8s/job-system/scheduler-role.yaml`
  - `k8s/job-system/scheduler-rolebinding.yaml`
  - `k8s/job-system/scheduler-deployment.yaml`
- Extended DB layer for scheduler-safe transitions:
  - `pkg/job_system/db.py`
    - `mark_job_running` (`QUEUED -> RUNNING`, increments attempts)
    - `mark_job_terminal` (`RUNNING -> SUCCEEDED/FAILED`)

What was proven:

- Submitting a success workload via API produced:
  - DB row in `QUEUED`
  - Scheduler-created Kubernetes Job labeled with `job-system/job-id=<job_id>`
  - API-observed transition `RUNNING -> SUCCEEDED`
- Submitting a failing workload via API produced:
  - Scheduler-created Kubernetes Job
  - API-observed transition to `FAILED`
  - Failure reason persisted in `last_error`
- DB query confirms both jobs with transition timestamps (`created_at`, `started_at`, `finished_at`) and attempts.

Evidence:

- `docs/evidence/phase3/m3.3/outputs/01-submit-job-succeeds.txt`
- `docs/evidence/phase3/m3.3/outputs/02-kubectl-get-jobs.txt`
- `docs/evidence/phase3/m3.3/outputs/03-kubectl-describe-job.txt`
- `docs/evidence/phase3/m3.3/outputs/04-kubectl-logs-job-pod.txt`
- `docs/evidence/phase3/m3.3/outputs/05-api-get-job-running.txt`
- `docs/evidence/phase3/m3.3/outputs/06-api-get-job-succeeded.txt`
- `docs/evidence/phase3/m3.3/outputs/07-db-state-transitions.txt`
- `docs/evidence/phase3/m3.3/outputs/08-submit-job-fails.txt`
- `docs/evidence/phase3/m3.3/outputs/09-api-get-job-failed.txt`
- `docs/evidence/phase3/m3.3/runbook.md`
- `docs/evidence/phase3/m3.3/commands.txt`

## 16) Phase 3 M3.4 - Reliability Layer

What changed:

- Added migration for retry scheduling:
  - `db/migrations/002_m3_4_reliability.sql`
  - Adds `next_retry_at` + dispatch-ready index.
- Extended domain/repository:
  - `pkg/job_system/models.py` adds `next_retry_at`
  - `pkg/job_system/db.py` adds:
    - `list_dispatchable_jobs` (`QUEUED` + `next_retry_at <= now`)
    - `mark_job_for_retry`
    - `compute_next_retry_at`
    - `mark_job_running` now resets per-attempt `started_at`
- Extended scheduler reliability behavior:
  - `services/scheduler/main.py`
    - retries failed jobs when `attempts < max_retries`
    - computes increasing retry delay via `next_retry_at`
    - enforces timeout (`last_error=timeout`)
    - terminates timed-out Kubernetes Jobs
    - detects missing K8s Job for `RUNNING` rows and marks failed
    - attempt-specific K8s Job naming/labels (`job-system/attempt`)
- RBAC updated to allow scheduler to delete Jobs for timeout enforcement:
  - `k8s/job-system/scheduler-role.yaml`

What was proven:

- Retry policy works: flaky job advanced through attempts and requeued until retry budget exhausted.
- Backoff gate works: scheduler only re-dispatches when `next_retry_at` is due.
- Timeout enforcement works: long-running job marked `FAILED` with `last_error=timeout`, backing K8s workload terminated.
- Scheduler restart safety works: deleting scheduler pod did not lose in-flight processing; job reached terminal state after pod replacement.

Evidence:

- `docs/evidence/phase3/m3.4/01-submit-flaky-job.txt`
- `docs/evidence/phase3/m3.4/02-retry-attempts-api.txt`
- `docs/evidence/phase3/m3.4/03-scheduler-logs-retry.txt`
- `docs/evidence/phase3/m3.4/04-backoff-timeline.txt`
- `docs/evidence/phase3/m3.4/05-submit-timeout-job.txt`
- `docs/evidence/phase3/m3.4/06-k8s-job-terminated-timeout.txt`
- `docs/evidence/phase3/m3.4/07-api-job-failed-timeout.txt`
- `docs/evidence/phase3/m3.4/08-restart-scheduler-proof.txt`
- `docs/evidence/phase3/m3.4/runbook.md`
- `docs/evidence/phase3/m3.4/commands.txt`

## Notes

Full raw outputs are stored in `docs/evidence/`:

- `01-get-deploy-rs-pods-svc.txt`
- `02-describe-deploy-web.txt`
- `03-describe-svc-web-svc.txt`
- `04-events-last-30.txt`
- `05-get-nodes-wide.txt`
- `06-get-pods-wide-after-scale.txt`
- `07-runtime-oom-get-pods.txt`
- `08-runtime-oom-describe-pod.txt`
- `09-runtime-oom-logs-previous.txt`
- `10-node-describe-with-taint.txt`
- `11-taint-test-running-get-pod.txt`
- `11a-taint-test-pending-describe-pod.txt`
- `12-taint-test-running-describe-pod.txt`
- `13-node-selector-describe-pod.txt`
- `14-node-affinity-describe-pod.txt`
- `15-node-selection-pods-wide.txt`
- `16-after-label-removal-pods-wide.txt`
- `18-qos-best-effort-describe-pod.txt`
- `19-qos-burstable-describe-pod.txt`
- `20-qos-guaranteed-describe-pod.txt`
- `21-qos-pressure-pods-wide.txt`
- `22-qos-pressure-events-last-120.txt`
- `23-node-describe-after-pressure.txt`
- `24-node-memorypressure-summary.txt`
- `25-evict-rerun-get-pods-wide.txt`
- `26-evict-rerun-events-last-200.txt`
- `27-evict-rerun-describe-qos-best-effort.txt`
- `28-evict-rerun-describe-node.txt`
- `29-evict-rerun-describe-evicted-pod.txt`
- `30-model-serving-and-eviction-current-pods.txt`
- `31-model-serving-resources.txt`
- `32-model-serving-top-nodes.txt`
- `33-model-serving-top-pods.txt`
- `34-model-serving-describe-hpa.txt`
- `35-model-serving-ingress-healthz.txt`
- `36-post-cleanup-pods.txt`
- `37-hpa-scale-loop-1.txt` ... `37-hpa-scale-loop-18.txt`
- `38-hpa-describe-after-loadgen.txt`
- `39-events-after-loadgen-last-200.txt`
- `40-loadgen-job-status.yaml`
- `41-loadgen-job-ttl-cleanup.txt`
- `42-model-server-deploy-after-hpa.txt`
- `43-model-server-pods-after-hpa.txt`
- `44-model-server-top-pods-after-scale.txt`
- `45-hpa-final-wide.txt`
- `46-hpa-before-load.txt`
- `47-deploy-before-load.txt`
- `48-pods-before-load.txt`
- `49-hpa-timeline-1.txt` ... `49-hpa-timeline-56.txt`
- `50-hpa-after-load.txt`
- `51-deploy-after-load.txt`
- `52-pods-after-load.txt`
- `53-events-hpa-updown-last-250.txt`
- `54-hpa-scale-timeline.md`
- `55-hpa-describe-final.txt`

## 17) Phase 3 M3.5 - Observability Layer (Metrics + Log Correlation)

What changed:

- Added shared Prometheus metrics module:
  - `pkg/job_system/metrics.py`
- Extended repository for metrics aggregation:
  - `pkg/job_system/db.py`
    - `get_status_counts()`
    - `get_reliability_totals()`
- Wired metrics endpoint in API:
  - `services/api/main.py` (`GET /metrics`)
- Wired scheduler metrics server and metric updates:
  - `services/scheduler/main.py`
    - serves metrics on `SCHEDULER_METRICS_PORT` (default `9000`)
    - refreshes queued/running gauges from DB
    - syncs success/fail/retry counters from DB totals
    - records latency histogram on terminal transitions
- Added Prometheus client dependency:
  - `services/api/requirements.txt`
  - `services/scheduler/requirements.txt`
  - `requirements-phase3.txt`
- Updated scheduler deployment for metrics port exposure:
  - `k8s/job-system/scheduler-deployment.yaml`

Required metrics implemented:

- Gauges:
  - `job_system_jobs_queued`
  - `job_system_jobs_running`
- Counters:
  - `job_system_job_success_total`
  - `job_system_job_fail_total`
  - `job_system_job_retries_total`
- Histogram:
  - `job_system_job_latency_seconds`

What was proven:

- Prometheus text exposition is available from scheduler `/metrics` and API `/metrics`.
- Metrics changed predictably across the workload lifecycle:
  - baseline: queued/running at `0`
  - during load: queued/running increased while jobs were being dispatched/executed
  - after drain: queued/running returned to `0` with terminal counters increased
- Structured logs include job correlation fields:
  - API emits `submit_created job_id=...`
  - Scheduler emits `k8s_job_created/job_running/job_succeeded/job_requeued_for_retry` with `job_id=...`

Evidence:

- `docs/evidence/phase3/m3.5/outputs/01-metrics-baseline.txt`
- `docs/evidence/phase3/m3.5/outputs/02-submit-20-jobs.txt`
- `docs/evidence/phase3/m3.5/outputs/03-metrics-during-load.txt`
- `docs/evidence/phase3/m3.5/outputs/04-metrics-after-drain.txt`
- `docs/evidence/phase3/m3.5/outputs/05-logs-correlation.txt`
- `docs/evidence/phase3/m3.5/runbook.md`
- `docs/evidence/phase3/m3.5/commands.txt`

## 18) M0 - Production Workflow Foundation

What changed:

- Added Phase 4 planning document in repo docs convention:
  - `docs/plans/phase4.md`
- Added ADR scaffolding:
  - `docs/adr/README.md`
  - `docs/adr/0000-template.md`
  - `docs/adr/0004-tenant-identity-source.md`
- Added PR and issue governance templates:
  - `.github/pull_request_template.md`
  - `.github/ISSUE_TEMPLATE/milestone.yml`
  - `.github/ISSUE_TEMPLATE/bug.yml`
- Added code ownership file:
  - `.github/CODEOWNERS`
- Added evidence automation scripts:
  - `scripts/evidence_init.sh`
  - `scripts/evidence_check.sh`
  - usage guide `docs/runbooks/evidence-workflow.md`
- Updated CI to enforce workflow foundations:
  - `.github/workflows/ci.yml` now checks lint, unit tests, and evidence scripts existence/executability.

What was proven:

- Repository conventions (planning docs, evidence structure, CI locations) were inspected and captured.
- Local unit tests and lint command executed successfully.
- Evidence init/check scripts run successfully for help/init paths and deterministically fail when `outputs/01-*.txt` is absent.

M0 evidence:

- `docs/evidence/m0/runbook.md`
- `docs/evidence/m0/commands.txt`
- `docs/evidence/m0/outputs/01-repo-structure.txt`
- `docs/evidence/m0/outputs/02-ci-or-tests.txt`
- `docs/evidence/m0/outputs/03-evidence-scripts.txt`

## 19) Phase 4 M4.1 - Tenant Identity + Per-Tenant Concurrency Quotas

What changed:

- Added migration for tenant identity:
  - `db/migrations/003_m4_1_tenant_identity.sql`
  - adds `jobs.tenant_id` (`NOT NULL`, backfilled with `tenant_default` for existing rows)
  - adds tenant-aware indexes (`idx_jobs_tenant_status`, `idx_jobs_tenant_status_created`)
- Updated domain model:
  - `pkg/job_system/models.py` adds `tenant_id` on `Job`
- Updated repository/persistence layer:
  - `pkg/job_system/db.py`
    - `create_job(..., tenant_id=...)` persists tenant on submit
    - `count_running_jobs_by_tenant(tenant_id)` for scheduler quota checks
- Updated API submit contract:
  - `services/api/main.py`
    - requires `X-Tenant-Id`
    - validation: non-empty, `<= 64`, pattern `^[A-Za-z0-9_-]{1,64}$`
    - deterministic 400 for missing/invalid tenant header
    - idempotency key conflict if same key is reused across different tenants
- Updated scheduler dispatch gate:
  - `services/scheduler/main.py`
    - new env-driven quota: `TENANT_MAX_RUNNING` (default `2`)
    - skips dispatch when tenant running count is at limit
- Updated scheduler manifest defaults:
  - `k8s/job-system/scheduler-deployment.yaml` adds `TENANT_MAX_RUNNING`
- Added tests:
  - `tests/test_m3_2_api.py`
    - missing tenant header fails
    - tenant_id persists on successful submit
  - `tests/test_m4_1_scheduler_quota.py`
    - verifies only one running job for same tenant when limit is 1

What was proven:

- Migration can be applied and schema/indexes prove tenant_id storage/query support.
- API rejects missing tenant header and accepts valid tenant header.
- Tenant identity is persisted and visible on readback.
- Scheduler quota gate prevents overscheduling for a single tenant.
- Lint and unit tests pass with new M4.1 behavior.

Evidence:

- `docs/evidence/phase4/m4.1/outputs/01-repo-structure.txt`
- `docs/evidence/phase4/m4.1/outputs/02-db-migration-status.txt`
- `docs/evidence/phase4/m4.1/outputs/03-api-tenant-validation.txt`
- `docs/evidence/phase4/m4.1/outputs/04-scheduler-tenant-quota.txt`
- `docs/evidence/phase4/m4.1/outputs/05-tests.txt`
- `docs/evidence/phase4/m4.1/runbook.md`
- `docs/evidence/phase4/m4.1/commands.txt`

## 20) Phase 0 P0.1 - System Map + Component Boundaries

What changed:

- Added architecture overview doc:
  - `docs/architecture/system-overview.md`
- Added component boundaries doc:
  - `docs/architecture/component-boundaries.md`
- Added architecture links in `README.md` under repository layout.
- Added Phase 0 evidence pack:
  - `docs/evidence/phase0/p0.1/runbook.md`
  - `docs/evidence/phase0/p0.1/commands.txt`
  - `docs/evidence/phase0/p0.1/outputs/*`

What was proven:

- Repository component inspection was captured before documentation edits.
- Architecture docs exist with control/data flow and ownership boundaries.
- README links resolve to the new architecture docs.
- Evidence pack passes `scripts/evidence_check.sh phase0 p0.1`.

Evidence:

- `docs/evidence/phase0/p0.1/runbook.md`
- `docs/evidence/phase0/p0.1/outputs/01-repo-component-map.txt`
- `docs/evidence/phase0/p0.1/outputs/02-architecture-docs.txt`
- `docs/evidence/phase0/p0.1/outputs/03-link-check.txt`

## 21) Phase 0 P0.2 - Job Lifecycle Contract (State Machine + Invariants)

What changed:

- Added lifecycle contract:
  - `docs/contracts/job-lifecycle.md`
- Added minimal README navigation link:
  - `docs/contracts/job-lifecycle.md`

What was proven:

- Status set was derived from current schema/runtime code:
  - `jobs.status`: `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELED`
  - `job_attempts.status`: includes `TIMED_OUT` (defined but not currently used by runtime transition writes)
- Implemented transitions were mapped to concrete API/scheduler/repository functions.
- Invariants were documented for tenant identity, tenant running quota (`TENANT_MAX_RUNNING`), retry/backoff gating (`next_retry_at`), and transition guards.
- Evidence pack passes lifecycle validation via `scripts/evidence_check.sh phase0 p0.2`.

Evidence:

- `docs/evidence/phase0/p0.2/runbook.md`
- `docs/evidence/phase0/p0.2/outputs/01-lifecycle-source-map.txt`
- `docs/evidence/phase0/p0.2/outputs/02-job-lifecycle-contract.txt`
- `docs/evidence/phase0/p0.2/outputs/03-transition-proof-pointers.txt`
- `docs/evidence/phase0/p0.2/outputs/04-evidence-check.txt`

## 22) Phase 0 P0.3 - API Contract + Tenant Model

What changed:

- Added API contract document:
  - `docs/contracts/api.md`
- Added README navigation link:
  - `docs/contracts/api.md`

What was proven:

- API endpoints and request/response models were enumerated directly from `services/api/main.py`.
- Tenant header extraction and validation (`X-Tenant-Id`) were mapped with deterministic error messages.
- Error model was documented from actual FastAPI `HTTPException` usage and validation constraints.
- Evidence pack for P0.3 passes `scripts/evidence_check.sh phase0 p0.3`.

Evidence:

- `docs/evidence/phase0/p0.3/runbook.md`
- `docs/evidence/phase0/p0.3/outputs/01-api-source-map.txt`
- `docs/evidence/phase0/p0.3/outputs/02-api-contract.txt`
- `docs/evidence/phase0/p0.3/outputs/03-error-model-proof.txt`
- `docs/evidence/phase0/p0.3/outputs/04-evidence-check.txt`

## 23) Phase 0 P0.4 - DB Schema Contract + Index/Migration Policy

What changed:

- Added DB schema contract:
  - `docs/contracts/db-schema.md`
- Added README contract navigation link:
  - `docs/contracts/db-schema.md`

What was proven:

- Schema source of truth was mapped to migration files under `db/migrations/`.
- `jobs` and `job_attempts` tables, constraints, and tenant fields were documented from code.
- Critical scheduler/API query patterns were mapped to required indexes with query-to-index proof pointers.
- Migration workflow was documented from repository runbook/README usage (`psql -f` against ordered SQL files).
- Evidence pack passes `scripts/evidence_check.sh phase0 p0.4`.

Evidence:

- `docs/evidence/phase0/p0.4/runbook.md`
- `docs/evidence/phase0/p0.4/outputs/01-db-source-map.txt`
- `docs/evidence/phase0/p0.4/outputs/02-db-schema-contract.txt`
- `docs/evidence/phase0/p0.4/outputs/03-index-to-query-mapping.txt`
- `docs/evidence/phase0/p0.4/outputs/04-migration-policy-proof.txt`
- `docs/evidence/phase0/p0.4/outputs/05-evidence-check.txt`

## 24) Phase 0 P0.5 - Operational Model (Local Dev, Scaling, Failure Modes, Observability)

What changed:

- Added operations documentation set:
  - `docs/operations/local-dev.md`
  - `docs/operations/scaling-and-ha.md`
  - `docs/operations/failure-modes.md`
  - `docs/operations/observability.md`
- Added README navigation links for operations docs.

What was proven:

- Local/dev run sources were mapped from README, manifests, Dockerfiles, scripts, and CI workflow.
- Runtime behavior under restart/failure was mapped from scheduler reconcile/retry/timeout code paths.
- Observability surfaces were documented from API/scheduler metric endpoints and shared metric definitions.
- Core failure modes were documented with detection and recovery guidance grounded in current implementation.
- Evidence pack validation passes `scripts/evidence_check.sh phase0 p0.5`.

Evidence:

- `docs/evidence/phase0/p0.5/runbook.md`
- `docs/evidence/phase0/p0.5/outputs/01-ops-source-map.txt`
- `docs/evidence/phase0/p0.5/outputs/02-operations-docs.txt`
- `docs/evidence/phase0/p0.5/outputs/03-observability-proof-pointers.txt`
- `docs/evidence/phase0/p0.5/outputs/04-failure-mode-proof-pointers.txt`
- `docs/evidence/phase0/p0.5/outputs/05-evidence-check.txt`

## 25) Phase 0 P0.6 - Architecture Diagram Artifact

What changed:

- Added dedicated architecture diagram doc:
  - `docs/architecture/diagram-overview.md`
- Updated README architecture links:
  - added `docs/architecture/diagram-overview.md`

What was proven:

- Existing architecture/lifecycle/contract docs were mapped before writing the new diagram artifact.
- A reviewer-friendly, standalone topology + execution-sequence diagram now exists.
- README navigation exposes the diagram directly for quick portfolio review.
- Evidence pack passes `scripts/evidence_check.sh phase0 p0.6`.

Evidence:

- `docs/evidence/phase0/p0.6/runbook.md`
- `docs/evidence/phase0/p0.6/outputs/01-source-map.txt`
- `docs/evidence/phase0/p0.6/outputs/02-diagram-doc.txt`
- `docs/evidence/phase0/p0.6/outputs/03-link-check.txt`
- `docs/evidence/phase0/p0.6/outputs/04-evidence-check.txt`

## 26) Phase 4 M4.2 - Fair Scheduling Across Tenants

What changed:

- Updated scheduler dispatch selection:
  - `services/scheduler/main.py`
  - Added round-robin ordering across tenant buckets for dispatchable candidates.
  - Added in-process fairness cursor (`_rr_last_tenant`) to rotate first-tenant selection across reconcile loops.
  - Added bounded candidate window multiplier (`SCHEDULER_FAIR_CANDIDATE_MULTIPLIER`, default `5`) to reduce starvation risk in single-tenant floods.
- Added fairness unit tests:
  - `tests/test_m4_2_fair_scheduling.py`

What was proven:

- Round-robin dispatch alternates tenants when both are eligible.
- Flood from one tenant does not starve another tenant within the eligible candidate window.
- Tenant quota enforcement from M4.1 remains active; over-limit tenant is skipped and other tenants continue dispatch.
- Deterministic ordering is preserved for fixed input and cursor state.
- Lint and tests pass.

Fairness limitations (current reality):

- RR cursor is in-memory in a single scheduler process.
- Multi-scheduler fairness/coordination is not addressed yet (requires M4.x HA coordination strategy).
- Fairness applies to the bounded dispatchable candidate set, not to the entire table in one query.

Evidence:

- `docs/evidence/phase4/m4.2/runbook.md`
- `docs/evidence/phase4/m4.2/outputs/01-scheduler-selection-map.txt`
- `docs/evidence/phase4/m4.2/outputs/02-round-robin-proof.txt`
- `docs/evidence/phase4/m4.2/outputs/03-no-starvation-proof.txt`
- `docs/evidence/phase4/m4.2/outputs/04-quota-interaction-proof.txt`
- `docs/evidence/phase4/m4.2/outputs/05-tests.txt`
- `docs/evidence/phase4/m4.2/outputs/06-evidence-check.txt`

## 27) Phase 4 M4.3 - Tenant-Scoped Reads + Audit Fields

What changed:

- Enforced tenant-scoped read/cancel behavior in API:
  - `services/api/main.py`
  - `GET /jobs/{job_id}`, `GET /jobs`, and `POST /jobs/{job_id}/cancel` now require `X-Tenant-Id`.
  - Cross-tenant access returns `404 Job not found` (resource-hiding policy).
- Added tenant-scoped repository methods:
  - `pkg/job_system/db.py`
  - Added `get_job_for_tenant`, `list_jobs_for_tenant`, and `update_job_status_for_tenant`.
- Added audit metadata fields for job creation:
  - `db/migrations/004_m4_3_tenant_scope_audit.sql`
  - `pkg/job_system/models.py`
  - `pkg/job_system/db.py`
  - `services/api/main.py`
  - Fields: `submitted_by`, `request_id`, `created_from_ip`.
- Updated contract docs:
  - `docs/contracts/api.md`
  - `docs/contracts/db-schema.md`
  - `README.md` migration steps include `004_m4_3_tenant_scope_audit.sql`.
- Added/updated unit tests:
  - `tests/test_m3_2_api.py`
  - Cross-tenant read/cancel denied, tenant-scoped list behavior, audit persistence.

What was proven:

- Tenant isolation is enforced for read/list/cancel paths with deterministic `404` on cross-tenant access.
- List endpoint returns only jobs for the requesting tenant.
- Cancel endpoint blocks cross-tenant cancellation and allows same-tenant cancellation.
- Audit fields are represented in model/repository, migration, and persisted create flow.
- Lint, tests, and evidence check pass for M4.3.

Evidence:

- `docs/evidence/phase4/m4.3/runbook.md`
- `docs/evidence/phase4/m4.3/outputs/01-api-db-scope-map.txt`
- `docs/evidence/phase4/m4.3/outputs/02-cross-tenant-read-denied.txt`
- `docs/evidence/phase4/m4.3/outputs/03-tenant-list-filter.txt`
- `docs/evidence/phase4/m4.3/outputs/04-cancel-tenant-scope.txt`
- `docs/evidence/phase4/m4.3/outputs/05-db-audit-fields.txt`
- `docs/evidence/phase4/m4.3/outputs/06-tests.txt`
- `docs/evidence/phase4/m4.3/outputs/07-evidence-check.txt`

## 28) Phase 4 M4.4 - Admission Control + Per-Tenant Rate Limiting

What changed:

- Added per-tenant submit throttling on API submit path:
  - `services/api/main.py`
  - In-memory token bucket limiter (`TenantRateLimiter`) with env-driven knobs:
    - `TENANT_SUBMIT_RPS` (default `2`)
    - `TENANT_SUBMIT_BURST` (default `5`)
  - Over-limit submit requests return:
    - HTTP `429`
    - body `{"detail":"Tenant submit rate limit exceeded; retry later"}`
    - `Retry-After` response header
- Added central submit admission caps in API:
  - `JOB_SUBMIT_MAX_PAYLOAD_BYTES` (default `16384`)
  - `JOB_SUBMIT_MAX_ENV_VARS` (default `64`)
  - `JOB_SUBMIT_MAX_ENV_KEY_LENGTH` (default `128`)
  - `JOB_SUBMIT_MAX_ENV_VALUE_LENGTH` (default `2048`)
  - `JOB_SUBMIT_MAX_RETRIES` (default `10`)
  - `JOB_SUBMIT_MAX_TIMEOUT_SECONDS` (default `86400`)
- Added M4.4 API tests:
  - `tests/test_m3_2_api.py`
  - Coverage for per-tenant throttling, cap violations, and non-regression paths.
- Updated API contract docs for throttling and admission behavior:
  - `docs/contracts/api.md`

What was proven:

- Burst submits for one tenant are throttled with deterministic `429` and `Retry-After`.
- Another tenant is not throttled by first-tenant overuse.
- Admission caps reject oversized/invalid submit payloads with deterministic `400` detail messages.
- Throttled submits do not create new job rows; accepted submits still persist.
- Lint and full unit tests pass.
- Evidence pack validation passes `scripts/evidence_check.sh phase4 m4.4`.

Limitations:

- Rate limiter state is in-memory and per API process.
- Limiter state resets on API restart and is not coordinated across multiple API replicas.

Evidence:

- `docs/evidence/phase4/m4.4/runbook.md`
- `docs/evidence/phase4/m4.4/outputs/01-admission-surface-map.txt`
- `docs/evidence/phase4/m4.4/outputs/02-rate-limit-burst.txt`
- `docs/evidence/phase4/m4.4/outputs/03-validation-caps.txt`
- `docs/evidence/phase4/m4.4/outputs/04-scheduler-stability-under-load.txt`
- `docs/evidence/phase4/m4.4/outputs/05-tests.txt`
- `docs/evidence/phase4/m4.4/outputs/06-evidence-check.txt`

## 29) Phase 4 M4.5 - Multi-Tenant Observability

What changed:

- Added tenant-aware observability metrics with bounded cardinality:
  - `pkg/job_system/metrics.py`
  - Strategy: hashed tenant buckets (`tenant_bucket=0..f`) instead of raw `tenant_id` labels.
- Added new bucketed and decision metrics:
  - `job_system_jobs_queued_by_tenant_bucket`
  - `job_system_jobs_running_by_tenant_bucket`
  - `job_system_scheduler_dispatch_decisions_total`
  - `job_system_scheduler_dispatch_decisions_by_tenant_bucket_total`
  - `job_system_scheduler_quota_blocks_total`
  - `job_system_scheduler_quota_blocks_by_tenant_bucket_total`
  - `job_system_api_submit_rate_limited_total`
  - `job_system_api_submit_rate_limited_by_tenant_bucket_total`
- Added API instrumentation and logs:
  - `services/api/main.py`
  - increments rate-limit metrics on throttled submits
  - logs `submit_created tenant_id=...` and `submit_rate_limited tenant_id=...`
- Added scheduler instrumentation and logs:
  - `services/scheduler/main.py`
  - records dispatch decisions (`dispatched`, `quota_skipped`, `no_candidates`)
  - records quota block counter per bucket
  - logs dispatch decisions with tenant correlation
- Added repository support for bucketed gauge refresh:
  - `pkg/job_system/db.py` (`get_status_counts_by_tenant_status`)
- Updated observability docs:
  - `docs/operations/observability.md`
- Extended tests for new metric surfacing:
  - `tests/test_m3_2_api.py`

What was proven:

- Baseline metrics expose all new multi-tenant observability metric names.
- Two-tenant load changes queued/running gauges and dispatch decision counters.
- Quota skip and API rate-limited events increment dedicated counters.
- API and scheduler logs include tenant-correlated decision lines for submit/dispatch/throttle paths.
- Lint and unit tests pass.
- Evidence check passes `scripts/evidence_check.sh phase4 m4.5`.

Cardinality strategy:

- Bounded hashed bucket labels (`tenant_bucket=0..f`) were chosen to preserve multi-tenant visibility without unbounded label growth.

Evidence:

- `docs/evidence/phase4/m4.5/runbook.md`
- `docs/evidence/phase4/m4.5/outputs/01-observability-surface-map.txt`
- `docs/evidence/phase4/m4.5/outputs/02-metrics-baseline.txt`
- `docs/evidence/phase4/m4.5/outputs/03-metrics-two-tenants-load.txt`
- `docs/evidence/phase4/m4.5/outputs/04-metrics-quota-and-rate-limit.txt`
- `docs/evidence/phase4/m4.5/outputs/05-logs-correlation-tenant.txt`
- `docs/evidence/phase4/m4.5/outputs/06-tests.txt`
- `docs/evidence/phase4/m4.5/outputs/07-evidence-check.txt`
