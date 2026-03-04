# PHASE4 M4.2 Runbook

## Goal
Implement and prove fair dispatch ordering across tenants using round-robin scheduling while preserving tenant quota enforcement.

## Steps
1. Inspect scheduler selection and DB ordering paths.
2. Implement round-robin ordering for bounded dispatchable candidates.
3. Keep tenant quota check behavior from M4.1.
4. Add unit tests for alternation, no-starvation, quota interaction, and deterministic ordering.
5. Capture proof outputs and run evidence check.

## Expected Results
- Dispatch order alternates tenants when both are eligible.
- Flooding by one tenant does not starve another tenant present in the eligible candidate window.
- Tenant quota still skips over-limit tenants and continues with other tenants.
- Tests and lint pass.
