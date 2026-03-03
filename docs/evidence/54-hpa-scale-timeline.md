# HPA Scale Timeline

Baseline snapshot:
- See `46-hpa-before-load.txt` (replicas at min, before loadgen)

Autoscaler rescale events (from `kubectl describe hpa model-server-hpa`):

| Event line |
|---|
| Normal   SuccessfulRescale             52m                  horizontal-pod-autoscaler  New size: 4; reason: cpu resource utilization (percentage of request) above target |
| Normal   SuccessfulRescale             52m                  horizontal-pod-autoscaler  New size: 6; reason: cpu resource utilization (percentage of request) above target |
| Normal   SuccessfulRescale             45m                  horizontal-pod-autoscaler  New size: 2; reason: All metrics below target |
| Normal   SuccessfulRescale             10m                  horizontal-pod-autoscaler  New size: 4; reason: cpu resource utilization (percentage of request) above target |
| Normal   SuccessfulRescale             10m                  horizontal-pod-autoscaler  New size: 6; reason: cpu resource utilization (percentage of request) above target |
| Normal   SuccessfulRescale             4m                   horizontal-pod-autoscaler  New size: 2; reason: All metrics below target |

Final snapshot:
- See `50-hpa-after-load.txt` and `51-deploy-after-load.txt` (replicas returned to min)
