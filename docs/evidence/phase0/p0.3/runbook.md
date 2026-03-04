# PHASE0 P0.3 Runbook

## Goal
Capture and document the API contract and tenant model from the current implementation.

## Steps
1. Confirm branch context and clean working state.
2. Inspect API entrypoint, endpoint definitions, request/response models, and header validation.
3. Inspect deployment/service wiring to document base URL/port behavior.
4. Author `docs/contracts/api.md` from discovered behavior only.
5. Add minimal README navigation link.
6. Capture evidence outputs (`01`-`04`) and run evidence validation.
7. Update reflection with P0.3 summary and links.

## Expected Result
- API contract reflects current code reality.
- Tenant header and error model are documented with deterministic examples.
- Evidence pack is reproducible and passes `scripts/evidence_check.sh phase0 p0.3`.
