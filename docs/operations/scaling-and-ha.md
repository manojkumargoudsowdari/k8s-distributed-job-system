# Scaling and HA

## Current Scaling Stance

## API
- API process is stateless for request handling.
- API can be horizontally scaled at deployment level.
- Shared state is externalized to Postgres via repository calls.

## Scheduler
- Current deployment sets `replicas: 1`.
- No leader election or DB claim-lock strategy is implemented.
- Multi-replica scheduler operation is not supported as an HA contract yet.

## Database
- Postgres deployment in `k8s/job-system/postgres.yaml` is single-replica and ephemeral (no PVC).
- DB is a single point of failure in current local/dev topology.

## Failure/Restart Behavior

### Scheduler restarts mid-run
- On restart, scheduler reconcile loop reloads from DB.
- `RUNNING` rows are rechecked against Kubernetes jobs.
- Missing backing k8s job is marked failed; existing jobs continue reconciliation.

### API restarts mid-submit
- API writes go through transaction-scoped repository methods.
- Idempotency key logic can return existing job if duplicate submit is retried with same payload+tenant.
- Client-side retry with same `Idempotency-Key` is recommended for uncertain responses.

### DB temporarily unavailable
- API/scheduler DB operations fail fast at query time.
- Scheduler loop cannot dispatch/reconcile while DB is down.
- Recovery path is restore DB connectivity, then scheduler/API continue from persisted state.

## Known Bottlenecks and Next Improvements
- Scheduler single instance limits throughput and HA.
- DB dependency for every control-plane transition can bottleneck at higher load.
- Current quota policy is per tenant (`TENANT_MAX_RUNNING`) but fairness and stronger admission control are follow-on work.
- Planned hardening path (Phase 4+):
  - stronger multi-tenant fairness
  - request rate limiting/admission controls
  - additional query/index tuning
  - multi-scheduler safety (leader election or DB claim model)
