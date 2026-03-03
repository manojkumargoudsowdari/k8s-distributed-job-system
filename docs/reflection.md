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

## Notes

Full raw outputs are stored in `docs/evidence/`:

- `01-get-deploy-rs-pods-svc.txt`
- `02-describe-deploy-web.txt`
- `03-describe-svc-web-svc.txt`
- `04-events-last-30.txt`
- `05-get-nodes-wide.txt`
- `06-get-pods-wide-after-scale.txt`
