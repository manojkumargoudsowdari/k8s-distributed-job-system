"""M3.1 smoke script: create/get/list/update a job record in Postgres."""

from __future__ import annotations

import os
from uuid import UUID

from pkg.job_system.db import JobRepository


def main() -> None:
    dsn = os.environ.get("JOB_SYSTEM_DB_DSN")
    if not dsn:
        raise RuntimeError("JOB_SYSTEM_DB_DSN is required")

    repo = JobRepository(dsn)
    try:
        created = repo.create_job(
            image="python:3.12-slim",
            command=["python", "-c"],
            args=["print('hello')"],
            queue="default",
            max_retries=2,
            idempotency_key="m3-1-smoke-1",
        )
        print(f"CREATED {created.id} status={created.status}")

        loaded = repo.get_job(UUID(str(created.id)))
        print(f"FETCHED {loaded.id} status={loaded.status}")

        repo.update_job_status(created.id, "RUNNING")
        repo.update_job_status(created.id, "SUCCEEDED")

        latest = repo.get_job(created.id)
        print(f"FINAL {latest.id} status={latest.status}")

        queued = repo.list_jobs(status="QUEUED", limit=10)
        print(f"QUEUED_COUNT {len(queued)}")
    finally:
        repo.close()


if __name__ == "__main__":
    main()
