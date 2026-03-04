from __future__ import annotations

import unittest
from datetime import datetime, timezone
from uuid import uuid4

from pkg.job_system.models import Job
from services.scheduler.main import Scheduler


def _queued_job(tenant_id: str) -> Job:
    now = datetime.now(timezone.utc)
    return Job(
        id=uuid4(),
        tenant_id=tenant_id,
        image="busybox:1.36",
        command=["sh", "-c"],
        args=["echo hi"],
        queue="default",
        status="QUEUED",
        attempts=0,
        priority=0,
        max_retries=0,
        backoff_seconds=5,
        timeout_seconds=None,
        created_at=now,
        updated_at=now,
        queued_at=now,
        next_retry_at=now,
    )


class FakeRepo:
    def __init__(self, jobs: list[Job]) -> None:
        self.jobs = {job.id: job for job in jobs}
        self.mark_running_calls: list[str] = []

    def list_dispatchable_jobs(self, limit: int = 5) -> list[Job]:
        queued = [job for job in self.jobs.values() if job.status == "QUEUED"]
        return queued[:limit]

    def count_running_jobs_by_tenant(self, tenant_id: str) -> int:
        return sum(
            1
            for job in self.jobs.values()
            if job.tenant_id == tenant_id and job.status == "RUNNING"
        )

    def mark_job_running(self, job_id):
        job = self.jobs.get(job_id)
        if not job or job.status != "QUEUED":
            return None
        job.status = "RUNNING"
        job.attempts += 1
        self.mark_running_calls.append(str(job_id))
        return job


class SchedulerTenantQuotaTests(unittest.TestCase):
    def test_tenant_quota_limits_dispatch_to_one_running(self) -> None:
        jobs = [_queued_job("tenant-a"), _queued_job("tenant-a")]
        repo = FakeRepo(jobs)

        scheduler = Scheduler.__new__(Scheduler)
        scheduler.repo = repo
        scheduler.dispatch_batch_size = 5
        scheduler.tenant_max_running = 1
        scheduler._ensure_k8s_job_exists = lambda job, attempt: True

        scheduler._dispatch_queued_jobs()

        running = [job for job in repo.jobs.values() if job.status == "RUNNING"]
        queued = [job for job in repo.jobs.values() if job.status == "QUEUED"]

        self.assertEqual(len(running), 1)
        self.assertEqual(len(queued), 1)
        self.assertEqual(len(repo.mark_running_calls), 1)


if __name__ == "__main__":
    unittest.main()
