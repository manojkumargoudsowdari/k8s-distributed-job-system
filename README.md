# k8s-distributed-job-system

Distributed job processing system for Kubernetes learning focused on scheduling, scaling, and failure analysis.

## Cluster

- Cluster name: `ai-infra-lab`
- Context: `kind-ai-infra-lab`

`kubectl get nodes -o wide`:

```text
NAME                         STATUS   ROLES           AGE   VERSION   INTERNAL-IP   EXTERNAL-IP   OS-IMAGE                         KERNEL-VERSION                     CONTAINER-RUNTIME
ai-infra-lab-control-plane   Ready    control-plane   96s   v1.32.2   172.18.0.2    <none>        Debian GNU/Linux 12 (bookworm)   6.6.87.2-microsoft-standard-WSL2   containerd://2.0.2
```

## What Was Built

- Deployment manifest: `k8s/deployment-web.yaml`
- Service manifest: `k8s/service-web-svc.yaml`
- Evidence and reflection: `docs/reflection.md`
- Raw command outputs: `docs/evidence/`

## Forced Failure: Insufficient Resources

- I intentionally set pod requests/limits to `cpu: "10"` and `memory: "20Gi"`.
- Result: pod stayed `Pending`.
- Scheduler event:
  `0/1 nodes are available: 1 Insufficient memory`.

## Fix Applied

- Restored schedulable resources:
  - Requests: `cpu: "100m"`, `memory: "128Mi"`
  - Limits: `cpu: "500m"`, `memory: "512Mi"`
- Re-applied manifest and rollout succeeded with `3/3` available replicas.

## Key Takeaways

- Scheduler decisions are governed first by `requests` against allocatable node capacity.
- `limits` cap runtime usage, but unschedulable `requests` block placement before container start.
- `kubectl describe pod` and Events provide the exact scheduling failure reason and should drive debugging.
