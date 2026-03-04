from __future__ import annotations

import unittest
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from pkg.job_system.models import Job
from services.api.main import TenantRateLimiter, app, get_repository, get_submit_limiter


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
        submitted_by: str | None = None,
        request_id: str | None = None,
        created_from_ip: str | None = None,
    ) -> Job:
        now = datetime.now(timezone.utc)
        job = Job(
            id=uuid4(),
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            submitted_by=submitted_by,
            request_id=request_id,
            created_from_ip=created_from_ip,
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

    def get_job_for_tenant(self, tenant_id: str, job_id: UUID) -> Job | None:
        job = self.jobs.get(job_id)
        if not job or job.tenant_id != tenant_id:
            return None
        return job

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

    def list_jobs_for_tenant(
        self, tenant_id: str, status: str | None = None, limit: int = 50
    ) -> list[Job]:
        values = [job for job in self.jobs.values() if job.tenant_id == tenant_id]
        if status:
            values = [job for job in values if job.status == status]
        return values[:limit]

    def get_status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for job in self.jobs.values():
            counts[job.status] = counts.get(job.status, 0) + 1
        return counts

    def get_status_counts_by_tenant_status(self) -> list[dict[str, Any]]:
        counts: dict[tuple[str, str], int] = {}
        for job in self.jobs.values():
            key = (job.tenant_id, job.status)
            counts[key] = counts.get(key, 0) + 1
        return [
            {"tenant_id": tenant_id, "status": status, "count": count}
            for (tenant_id, status), count in counts.items()
        ]

    def get_reliability_totals(self) -> dict[str, int]:
        return {
            "success_total": sum(1 for job in self.jobs.values() if job.status == "SUCCEEDED"),
            "fail_total": sum(1 for job in self.jobs.values() if job.status == "FAILED"),
            "retries_total": sum(max(job.attempts - 1, 0) for job in self.jobs.values()),
        }

    def update_job_status(self, job_id: UUID, status: str, error: str | None = None) -> Job | None:
        job = self.jobs.get(job_id)
        if not job:
            return None
        job.status = status
        job.last_error = error
        job.updated_at = datetime.now(timezone.utc)
        self.jobs[job_id] = job
        return job

    def update_job_status_for_tenant(
        self, tenant_id: str, job_id: UUID, status: str, error: str | None = None
    ) -> Job | None:
        job = self.jobs.get(job_id)
        if not job or job.tenant_id != tenant_id:
            return None
        return self.update_job_status(job_id, status, error)


class JobApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = FakeRepository()
        app.dependency_overrides[get_repository] = lambda: self.repo
        app.dependency_overrides[get_submit_limiter] = lambda: TenantRateLimiter(
            rps=1000.0, burst=1000
        )
        self.client = TestClient(app)
        self._saved_env = {
            "JOB_SUBMIT_MAX_PAYLOAD_BYTES": os.getenv("JOB_SUBMIT_MAX_PAYLOAD_BYTES"),
            "JOB_SUBMIT_MAX_ENV_VARS": os.getenv("JOB_SUBMIT_MAX_ENV_VARS"),
            "JOB_SUBMIT_MAX_ENV_KEY_LENGTH": os.getenv("JOB_SUBMIT_MAX_ENV_KEY_LENGTH"),
            "JOB_SUBMIT_MAX_ENV_VALUE_LENGTH": os.getenv("JOB_SUBMIT_MAX_ENV_VALUE_LENGTH"),
            "JOB_SUBMIT_MAX_RETRIES": os.getenv("JOB_SUBMIT_MAX_RETRIES"),
            "JOB_SUBMIT_MAX_TIMEOUT_SECONDS": os.getenv("JOB_SUBMIT_MAX_TIMEOUT_SECONDS"),
        }

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

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
        self.repo.create_job(image="busybox:1.36", tenant_id="tenant-b")

        response = self.client.get(
            "/jobs",
            params={"status": "RUNNING"},
            headers={"X-Tenant-Id": "tenant-a"},
        )
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

    def test_get_job_requires_tenant_header(self) -> None:
        job = self.repo.create_job(image="busybox:1.36", tenant_id="tenant-a")
        response = self.client.get(f"/jobs/{job.id}")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "X-Tenant-Id header is required")

    def test_cross_tenant_get_returns_not_found(self) -> None:
        job = self.repo.create_job(image="busybox:1.36", tenant_id="tenant-a")
        response = self.client.get(
            f"/jobs/{job.id}", headers={"X-Tenant-Id": "tenant-b"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Job not found")

    def test_tenant_scoped_list(self) -> None:
        job_a = self.repo.create_job(image="busybox:1.36", tenant_id="tenant-a")
        self.repo.create_job(image="busybox:1.36", tenant_id="tenant-b")

        response = self.client.get("/jobs", headers={"X-Tenant-Id": "tenant-a"})
        self.assertEqual(response.status_code, 200)
        jobs = response.json()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["id"], str(job_a.id))
        self.assertEqual(jobs[0]["tenant_id"], "tenant-a")

    def test_cross_tenant_cancel_denied_by_not_found(self) -> None:
        job = self.repo.create_job(image="busybox:1.36", tenant_id="tenant-a")
        response = self.client.post(
            f"/jobs/{job.id}/cancel", headers={"X-Tenant-Id": "tenant-b"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Job not found")

    def test_same_tenant_cancel_allowed(self) -> None:
        job = self.repo.create_job(image="busybox:1.36", tenant_id="tenant-a")
        response = self.client.post(
            f"/jobs/{job.id}/cancel", headers={"X-Tenant-Id": "tenant-a"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "CANCELED")

    def test_submit_persists_audit_fields(self) -> None:
        response = self.client.post(
            "/jobs",
            json={"image": "busybox:1.36"},
            headers={
                "X-Tenant-Id": "tenant-a",
                "X-Submitted-By": "alice",
                "X-Request-Id": "req-123",
            },
        )
        self.assertEqual(response.status_code, 201)
        job_id = UUID(response.json()["job_id"])
        job = self.repo.get_job(job_id)
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job.submitted_by, "alice")
        self.assertEqual(job.request_id, "req-123")

    def test_rate_limit_applies_per_tenant(self) -> None:
        limiter = TenantRateLimiter(rps=1.0, burst=1)
        app.dependency_overrides[get_submit_limiter] = lambda: limiter
        payload = {"image": "busybox:1.36"}

        first_a = self.client.post(
            "/jobs", json=payload, headers={"X-Tenant-Id": "tenant-a"}
        )
        second_a = self.client.post(
            "/jobs", json=payload, headers={"X-Tenant-Id": "tenant-a"}
        )
        first_b = self.client.post(
            "/jobs", json=payload, headers={"X-Tenant-Id": "tenant-b"}
        )

        self.assertEqual(first_a.status_code, 201)
        self.assertEqual(second_a.status_code, 429)
        self.assertEqual(first_b.status_code, 201)
        self.assertEqual(second_a.headers.get("Retry-After"), "1")
        self.assertEqual(
            second_a.json()["detail"], "Tenant submit rate limit exceeded; retry later"
        )

    def test_submit_rejects_payload_over_cap(self) -> None:
        os.environ["JOB_SUBMIT_MAX_PAYLOAD_BYTES"] = "120"
        response = self.client.post(
            "/jobs",
            headers={"X-Tenant-Id": "tenant-a"},
            json={
                "image": "busybox:1.36",
                "command": ["sh", "-c"],
                "args": ["echo " + ("x" * 200)],
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("JOB_SUBMIT_MAX_PAYLOAD_BYTES", response.json()["detail"])

    def test_submit_rejects_env_caps(self) -> None:
        os.environ["JOB_SUBMIT_MAX_ENV_VARS"] = "1"
        response_too_many = self.client.post(
            "/jobs",
            headers={"X-Tenant-Id": "tenant-a"},
            json={
                "image": "busybox:1.36",
                "env": {"A": "1", "B": "2"},
            },
        )
        self.assertEqual(response_too_many.status_code, 400)
        self.assertIn("JOB_SUBMIT_MAX_ENV_VARS", response_too_many.json()["detail"])

        os.environ["JOB_SUBMIT_MAX_ENV_VARS"] = "10"
        os.environ["JOB_SUBMIT_MAX_ENV_KEY_LENGTH"] = "3"
        response_key_len = self.client.post(
            "/jobs",
            headers={"X-Tenant-Id": "tenant-a"},
            json={"image": "busybox:1.36", "env": {"TOOLONG": "1"}},
        )
        self.assertEqual(response_key_len.status_code, 400)
        self.assertIn("JOB_SUBMIT_MAX_ENV_KEY_LENGTH", response_key_len.json()["detail"])

    def test_submit_rejects_retries_and_timeout_caps(self) -> None:
        os.environ["JOB_SUBMIT_MAX_RETRIES"] = "2"
        retries_response = self.client.post(
            "/jobs",
            headers={"X-Tenant-Id": "tenant-a"},
            json={"image": "busybox:1.36", "max_retries": 3},
        )
        self.assertEqual(retries_response.status_code, 400)
        self.assertIn("JOB_SUBMIT_MAX_RETRIES", retries_response.json()["detail"])

        os.environ["JOB_SUBMIT_MAX_TIMEOUT_SECONDS"] = "30"
        timeout_response = self.client.post(
            "/jobs",
            headers={"X-Tenant-Id": "tenant-a"},
            json={"image": "busybox:1.36", "timeout_seconds": 31},
        )
        self.assertEqual(timeout_response.status_code, 400)
        self.assertIn(
            "JOB_SUBMIT_MAX_TIMEOUT_SECONDS", timeout_response.json()["detail"]
        )

    def test_metrics_expose_multitenant_observability_names(self) -> None:
        # Create two tenant jobs to ensure bucketed gauges can populate.
        self.client.post(
            "/jobs",
            json={"image": "busybox:1.36"},
            headers={"X-Tenant-Id": "tenant-a"},
        )
        self.client.post(
            "/jobs",
            json={"image": "busybox:1.36"},
            headers={"X-Tenant-Id": "tenant-b"},
        )
        # Trigger one rate-limit event to ensure API rate-limited metrics exist.
        limiter = TenantRateLimiter(rps=1.0, burst=1)
        app.dependency_overrides[get_submit_limiter] = lambda: limiter
        self.client.post(
            "/jobs",
            json={"image": "busybox:1.36"},
            headers={"X-Tenant-Id": "tenant-c"},
        )
        self.client.post(
            "/jobs",
            json={"image": "busybox:1.36"},
            headers={"X-Tenant-Id": "tenant-c"},
        )

        metrics_response = self.client.get("/metrics")
        self.assertEqual(metrics_response.status_code, 200)
        body = metrics_response.text
        self.assertIn("job_system_jobs_queued_by_tenant_bucket", body)
        self.assertIn("job_system_jobs_running_by_tenant_bucket", body)
        self.assertIn("job_system_api_submit_rate_limited_total", body)
        self.assertIn(
            "job_system_api_submit_rate_limited_by_tenant_bucket_total",
            body,
        )


if __name__ == "__main__":
    unittest.main()
