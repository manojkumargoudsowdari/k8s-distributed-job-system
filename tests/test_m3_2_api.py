from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from pkg.job_system.models import Job
from services.api.main import app, get_repository


class FakeRepository:
    def __init__(self) -> None:
        self.jobs: dict[UUID, Job] = {}
        self.by_idempotency: dict[str, UUID] = {}

    def create_job(
        self,
        *,
        tenant_id: str,
        image: str,
        command: list[str] | None = None,
        args: list[str] | None = None,
        queue: str = "default",
        env: dict[str, Any] | None = None,
        resources: dict[str, Any] | None = None,
        priority: int = 0,
        max_retries: int = 0,
        backoff_seconds: int = 5,
        timeout_seconds: int | None = None,
        idempotency_key: str | None = None,
    ) -> Job:
        now = datetime.now(timezone.utc)
        job = Job(
            id=uuid4(),
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            queue=queue,
            image=image,
            command=command or [],
            args=args or [],
            env=env or {},
            resources=resources or {},
            priority=priority,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            timeout_seconds=timeout_seconds,
            status="QUEUED",
            attempts=0,
            desired_status=None,
            last_error=None,
            created_at=now,
            queued_at=now,
            started_at=None,
            finished_at=None,
            next_retry_at=now,
            updated_at=now,
        )
        self.jobs[job.id] = job
        if idempotency_key:
            self.by_idempotency[idempotency_key] = job.id
        return job

    def get_job(self, job_id: UUID) -> Job | None:
        return self.jobs.get(job_id)

    def get_job_by_idempotency_key(self, idempotency_key: str) -> Job | None:
        job_id = self.by_idempotency.get(idempotency_key)
        if not job_id:
            return None
        return self.jobs.get(job_id)

    def list_jobs(self, status: str | None = None, limit: int = 50) -> list[Job]:
        values = list(self.jobs.values())
        if status:
            values = [job for job in values if job.status == status]
        return values[:limit]

    def update_job_status(self, job_id: UUID, status: str, error: str | None = None) -> Job | None:
        job = self.jobs.get(job_id)
        if not job:
            return None
        job.status = status
        job.last_error = error
        job.updated_at = datetime.now(timezone.utc)
        self.jobs[job_id] = job
        return job


class JobApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = FakeRepository()
        app.dependency_overrides[get_repository] = lambda: self.repo
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_create_job(self) -> None:
        response = self.client.post(
            "/jobs",
            json={"image": "busybox:1.36", "command": ["echo"], "args": ["hi"]},
            headers={"X-Tenant-Id": "tenant-a"},
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertIn("job_id", body)
        self.assertEqual(body["status"], "QUEUED")

    def test_idempotent_repeat_returns_same_job_id(self) -> None:
        payload = {"image": "busybox:1.36", "command": ["echo"], "args": ["same"]}
        headers = {"Idempotency-Key": "abc-123", "X-Tenant-Id": "tenant-a"}

        first = self.client.post("/jobs", json=payload, headers=headers)
        second = self.client.post("/jobs", json=payload, headers=headers)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.json()["job_id"], second.json()["job_id"])

    def test_idempotency_conflict_different_payload(self) -> None:
        first_payload = {"image": "busybox:1.36", "args": ["a"]}
        second_payload = {"image": "busybox:1.36", "args": ["b"]}
        headers = {"Idempotency-Key": "same-key", "X-Tenant-Id": "tenant-a"}

        first = self.client.post("/jobs", json=first_payload, headers=headers)
        second = self.client.post("/jobs", json=second_payload, headers=headers)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 409)

    def test_list_filter_by_status(self) -> None:
        queued = self.repo.create_job(image="busybox:1.36", tenant_id="tenant-a")
        running = self.repo.create_job(image="busybox:1.36", tenant_id="tenant-a")
        self.repo.update_job_status(running.id, "RUNNING")

        response = self.client.get("/jobs", params={"status": "RUNNING"})
        self.assertEqual(response.status_code, 200)
        jobs = response.json()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["id"], str(running.id))
        self.assertNotEqual(jobs[0]["id"], str(queued.id))

    def test_submit_requires_tenant_header(self) -> None:
        response = self.client.post("/jobs", json={"image": "busybox:1.36"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "X-Tenant-Id header is required")

    def test_submit_with_tenant_persists_tenant_id(self) -> None:
        response = self.client.post(
            "/jobs",
            json={"image": "busybox:1.36"},
            headers={"X-Tenant-Id": "tenant-a"},
        )
        self.assertEqual(response.status_code, 201)
        job_id = UUID(response.json()["job_id"])
        job = self.repo.get_job(job_id)
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job.tenant_id, "tenant-a")


if __name__ == "__main__":
    unittest.main()
