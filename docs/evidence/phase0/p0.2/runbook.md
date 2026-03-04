# PHASE0 P0.2 Runbook

## Goal
Document the implemented job lifecycle state machine and invariants from current code reality.

## Steps
1. Confirm branch and clean workspace.
2. Inspect lifecycle sources (schema, model, API submit/cancel, scheduler transitions, DB transition methods).
3. Author `docs/contracts/job-lifecycle.md` from discovered transitions only.
4. Add minimal README link to contract doc.
5. Capture evidence outputs (`01`-`04`) and run evidence check.
6. Update reflection with P0.2 summary and links.

## Expected Result
- Lifecycle contract matches implemented statuses/transitions.
- Invariants include tenant quota and retry/backoff behavior.
- Evidence pack is reproducible and passes `scripts/evidence_check.sh phase0 p0.2`.
