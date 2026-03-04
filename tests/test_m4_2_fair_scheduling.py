from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pkg.job_system.models import Job
from services.scheduler.main import Scheduler


def _queued_job(tenant_id: str, offset_seconds: int = 0) -> Job:
    now = datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
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


def _running_job(tenant_id: str) -> Job:
    now = datetime.now(timezone.utc)
    return Job(
        id=uuid4(),
        tenant_id=tenant_id,
        image="busybox:1.36",
        command=["sh", "-c"],
        args=["echo running"],
        queue="default",
        status="RUNNING",
        attempts=1,
        priority=0,
        max_retries=0,
        backoff_seconds=5,
        timeout_seconds=None,
        created_at=now,
        updated_at=now,
        queued_at=now,
        started_at=now,
    )


class FakeRepo:
    def __init__(self, jobs: list[Job]) -> None:
        self.jobs = {job.id: job for job in jobs}
        self.job_order = [job.id for job in jobs]
        self.mark_running_tenants: list[str] = []

    def list_dispatchable_jobs(self, limit: int = 5) -> list[Job]:
        ordered = [self.jobs[job_id] for job_id in self.job_order]
        queued = [job for job in ordered if job.status == "QUEUED"]
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
        self.mark_running_tenants.append(job.tenant_id)
        return job


class SchedulerFairnessTests(unittest.TestCase):
    def _make_scheduler(self, repo: FakeRepo) -> Scheduler:
        scheduler = Scheduler.__new__(Scheduler)
        scheduler.repo = repo
        scheduler.dispatch_batch_size = 4
        scheduler.dispatch_candidate_multiplier = 5
        scheduler.tenant_max_running = 10
        scheduler._rr_last_tenant = None
        scheduler._ensure_k8s_job_exists = lambda job, attempt: True
        return scheduler

    def test_round_robin_alternates_tenants(self) -> None:
        jobs = [
            _queued_job("tenant-a"),
            _queued_job("tenant-a", 1),
            _queued_job("tenant-a", 2),
            _queued_job("tenant-a", 3),
            _queued_job("tenant-b"),
            _queued_job("tenant-b", 1),
            _queued_job("tenant-b", 2),
            _queued_job("tenant-b", 3),
        ]
        repo = FakeRepo(jobs)
        scheduler = self._make_scheduler(repo)

        scheduler._dispatch_queued_jobs()

        self.assertEqual(
            repo.mark_running_tenants[:4],
            ["tenant-a", "tenant-b", "tenant-a", "tenant-b"],
        )

    def test_no_starvation_when_one_tenant_floods(self) -> None:
        jobs = [
            _queued_job("tenant-a"),
            _queued_job("tenant-a", 1),
            _queued_job("tenant-a", 2),
            _queued_job("tenant-a", 3),
            _queued_job("tenant-a", 4),
            _queued_job("tenant-a", 5),
            _queued_job("tenant-b"),
            _queued_job("tenant-b", 1),
        ]
        repo = FakeRepo(jobs)
        scheduler = self._make_scheduler(repo)

        scheduler._dispatch_queued_jobs()

        self.assertIn("tenant-b", repo.mark_running_tenants[:4])

    def test_quota_skip_dispatches_other_tenant(self) -> None:
        jobs = [
            _running_job("tenant-a"),
            _queued_job("tenant-a"),
            _queued_job("tenant-b"),
            _queued_job("tenant-b", 1),
        ]
        repo = FakeRepo(jobs)
        scheduler = self._make_scheduler(repo)
        scheduler.tenant_max_running = 1

        scheduler._dispatch_queued_jobs()

        self.assertEqual(repo.mark_running_tenants, ["tenant-b"])

    def test_ordering_deterministic_for_same_input(self) -> None:
        jobs = [
            _queued_job("tenant-a"),
            _queued_job("tenant-a", 1),
            _queued_job("tenant-b"),
            _queued_job("tenant-b", 1),
        ]
        repo = FakeRepo(jobs)
        scheduler = self._make_scheduler(repo)

        ordered_1 = scheduler._order_dispatchable_jobs_round_robin(
            repo.list_dispatchable_jobs(limit=10)
        )
        ordered_2 = scheduler._order_dispatchable_jobs_round_robin(
            repo.list_dispatchable_jobs(limit=10)
        )

        self.assertEqual(
            [job.tenant_id for job in ordered_1],
            [job.tenant_id for job in ordered_2],
        )


if __name__ == "__main__":
    unittest.main()
