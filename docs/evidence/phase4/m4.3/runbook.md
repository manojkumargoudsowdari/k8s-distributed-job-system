# PHASE4 M4.3 Runbook

## Goal
Enforce tenant-scoped reads/cancel and add basic audit metadata persistence for submitted jobs.

## Steps
1. Inspect API routes, DB repository methods, migrations, and tests.
2. Add tenant validation dependency for GET/list/cancel endpoints.
3. Add tenant-scoped repository methods and tenant-scoped cancel update path.
4. Add audit fields (`submitted_by`, `request_id`, `created_from_ip`) to model, migration, and create path.
5. Update API contract docs to reflect tenant-scoped endpoints.
6. Add/extend unit tests for cross-tenant denial, tenant list filtering, tenant cancel scope, and audit persistence.
7. Capture deterministic evidence outputs and run evidence check.

## Expected Results
- GET/list/cancel require `X-Tenant-Id`.
- Cross-tenant read/cancel returns `404`.
- Tenant list only returns tenant-owned jobs.
- Audit fields persist on submit when headers are provided.
