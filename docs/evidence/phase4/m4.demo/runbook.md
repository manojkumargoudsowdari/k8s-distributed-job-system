# PHASE4 M4.Demo Runbook

## Goal
Provide a one-command live demo harness for Phase 4 behavior without changing core platform logic.

## Scope
- Demo script + docs/evidence + README pointer only.
- No API/scheduler/DB behavior changes.

## Prerequisites
- Python environment with project dependencies installed.
- Run from repository root.

## One command
```bash
bash scripts/demo_phase4_closeout.sh
```

## Environment knobs used by harness
- `TENANT_MAX_RUNNING` (default `1`)
- `TENANT_SUBMIT_RPS` (default `1`)
- `TENANT_SUBMIT_BURST` (default `1`)
- `SCHEDULER_METRICS_PORT` (default `9000`, script also probes local demo metrics port)
- Optional output override: `DEMO_OUTPUT_DIR` (default `docs/evidence/phase4/m4.demo/outputs`)

## Expected output proofs
- `outputs/03-tenant-isolation.txt`
  - shows cross-tenant `GET /jobs/{id}` -> `404`
- `outputs/04-fairness-quota.txt`
  - shows alternating tenant dispatch order + quota block log/metrics
- `outputs/05-rate-limit.txt`
  - shows burst submit `429` + `Retry-After` + rate-limit metric increment
- `outputs/06-metrics-scrape.txt`
  - shows API metrics excerpt and scheduler metrics scrape excerpt with non-zero values

## Determinism
- Filenames are stable.
- Script is idempotent and overwrites `03`-`06` outputs on rerun.
