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

## 12) HPA Scale-Up Assessment (Load Generator)

Goal:

- Force HPA CPU target breach and capture scale-up evidence.

Changes:

- Added CPU burn endpoint in app:
  - `GET /burn?ms=<n>` in `app/main.py`
- Added load generator Job:
  - `k8s/model-serving/model-server-loadgen-job.yaml`
  - 8 parallel workers repeatedly call `/burn`.
- Updated deployment image to `fastapi-model-server:0.1.1`.

Observed scaling:

- HPA scaled `model-server` from `2` -> `4` -> `6` replicas.
- HPA reached max replica bound (`maxReplicas: 6`) with `ScalingLimited=True`.
- Deployment confirmed at `6/6` available pods.

Key evidence:

- Time-series loop snapshots:
  - `37-hpa-scale-loop-1.txt` ... `37-hpa-scale-loop-18.txt`
- HPA describe with rescale events:
  - `38-hpa-describe-after-loadgen.txt`
- Cluster events containing:
  - `SuccessfulRescale`
  - `ScalingReplicaSet`
  - `39-events-after-loadgen-last-200.txt`
- Final state:
  - `42-model-server-deploy-after-hpa.txt`
  - `43-model-server-pods-after-hpa.txt`
  - `45-hpa-final-wide.txt`

Operational note:

- Job used `ttlSecondsAfterFinished: 120`, so completed Job/Pods were auto-removed.
- TTL cleanup evidence:
  - `41-loadgen-job-ttl-cleanup.txt`

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
