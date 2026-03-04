# PHASE0 P0.5 Runbook

## Goal
Document operational model for local development, scaling/HA posture, failure modes, and observability surfaces.

## Steps
1. Confirm branch and workspace state.
2. Inspect run sources (README, k8s manifests, Dockerfiles, CI workflow, scripts).
3. Inspect scheduler reliability behavior and API idempotency behavior.
4. Inspect metrics/logging implementation locations.
5. Author operations docs:
   - `docs/operations/local-dev.md`
   - `docs/operations/scaling-and-ha.md`
   - `docs/operations/failure-modes.md`
   - `docs/operations/observability.md`
6. Add minimal README links under an Operations docs section.
7. Capture deterministic evidence outputs and run evidence check.
8. Update reflection with P0.5 summary and evidence links.

## Expected Result
- Reproducible local/dev instructions for API + scheduler + DB.
- Explicit HA limitations and recovery behavior documented.
- Failure-mode table with detection/mitigation for core operational scenarios.
- Observability endpoints, metrics, and log correlation fields documented.
