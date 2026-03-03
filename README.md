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

## Local Quickstart (Kind + Model Serving)

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
