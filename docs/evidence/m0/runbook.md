# M0 Runbook — Production Workflow Foundation

## Goal
Establish production-grade workflow scaffolding before Phase 4 feature logic.

## Scope
- Repository workflow conventions inspection
- Phase 4 planning document standardization
- ADR scaffolding
- PR and issue templates
- CODEOWNERS
- CI gate updates
- Evidence helper scripts and validation

## Steps
1. Inspect repository structure, conventions, CI, and templates.
2. Record findings in `outputs/01-repo-structure.txt`.
3. Add/align workflow foundation docs and templates.
4. Add evidence helper scripts under `scripts/`.
5. Run tests/lint and capture proof in `outputs/02-ci-or-tests.txt`.
6. Run evidence scripts and capture proof in `outputs/03-evidence-scripts.txt`.
7. Update `docs/reflection.md` with M0 changes and proofs.

## Expected Outcome
- Workflow scaffolding exists and is tracked.
- CI checks lint/tests and validates evidence scripts are present/executable.
- M0 evidence pack is reproducible.
