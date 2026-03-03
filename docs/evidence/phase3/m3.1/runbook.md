# M3.1 Runbook: Domain + Postgres Persistence

## Scope

This runbook proves M3.1 acceptance:

- Postgres reachable
- Migration applied
- jobs schema and indexes exist
- sample insert/select and status transitions work

## Preconditions

- Docker running
- Repository root: `d:\Work\Code\Kubernetes\k8s-distributed-job-system`

## Execute

1. Start Postgres container (`job-system-postgres`) on `localhost:5433`
2. Apply migration `db/migrations/001_create_jobs.sql`
3. Inspect schema and indexes
4. Insert sample row and transition status QUEUED -> RUNNING -> SUCCEEDED
5. (Optional) run repository smoke script

## Evidence Files

Required acceptance files:

- `01-psql-connection.txt`
- `02-migration-applied.txt`
- `03-schema-jobs-table.txt`
- `04-indexes.txt`
- `05-sample-insert-select.txt`

Additional outputs:

- `outputs/06-python-deps-install.txt`
- `outputs/07-db-repository-smoke.txt`
