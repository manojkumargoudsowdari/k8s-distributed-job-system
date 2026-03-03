"""Scheduler service for Phase 3 M3.3.

Dispatches QUEUED jobs to Kubernetes Jobs and reconciles completion.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

from kubernetes import client, config
from kubernetes.client import ApiException

from pkg.job_system import Job, JobRepository, compute_next_retry_at

LOGGER = logging.getLogger("job-system-scheduler")


def _build_k8s_job_manifest(job: Job, namespace: str, attempt: int) -> client.V1Job:
    job_id = str(job.id)
    name = f"js-job-{job_id[:8]}-a{attempt}"
    labels = {
        "app": "job-system-task",
        "job-system/managed-by": "scheduler",
        "job-system/job-id": job_id,
        "job-system/attempt": str(attempt),
    }

    env_vars = []
    for key, value in (job.env or {}).items():
        env_vars.append(client.V1EnvVar(name=key, value=str(value)))

    container = client.V1Container(
        name="task",
        image=job.image,
        command=job.command or None,
        args=job.args or None,
        env=env_vars or None,
        resources=client.V1ResourceRequirements(**job.resources)
        if job.resources
        else None,
    )

    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels=labels),
        spec=client.V1PodSpec(
            restart_policy="Never",
            containers=[container],
        ),
    )

    spec = client.V1JobSpec(
        template=template,
        backoff_limit=0,
        ttl_seconds_after_finished=600,
    )
    return client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(name=name, namespace=namespace, labels=labels),
        spec=spec,
    )


class Scheduler:
    def __init__(self) -> None:
        dsn = os.getenv("DATABASE_URL")
        if not dsn:
            raise RuntimeError("DATABASE_URL is not set")

        self.namespace = os.getenv("SCHEDULER_NAMESPACE", "default")
        self.poll_interval_seconds = int(
            os.getenv("SCHEDULER_POLL_INTERVAL_SECONDS", "3")
        )
        self.dispatch_batch_size = int(os.getenv("SCHEDULER_DISPATCH_BATCH_SIZE", "5"))
        self.running_scan_limit = int(os.getenv("SCHEDULER_RUNNING_SCAN_LIMIT", "50"))

        self.repo = JobRepository(dsn)
        self.batch_api = self._load_batch_api()

    @staticmethod
    def _load_batch_api() -> client.BatchV1Api:
        try:
            config.load_incluster_config()
            LOGGER.info("Loaded in-cluster Kubernetes config")
        except config.ConfigException:
            config.load_kube_config()
            LOGGER.info("Loaded local kubeconfig")
        return client.BatchV1Api()

    def run_forever(self) -> None:
        LOGGER.info("Scheduler started")
        try:
            while True:
                self.reconcile_once()
                time.sleep(self.poll_interval_seconds)
        finally:
            self.repo.close()

    def reconcile_once(self) -> None:
        self._dispatch_queued_jobs()
        self._reconcile_running_jobs()

    def _dispatch_queued_jobs(self) -> None:
        queued_jobs = self.repo.list_dispatchable_jobs(limit=self.dispatch_batch_size)
        for job in queued_jobs:
            next_attempt = job.attempts + 1
            created = self._ensure_k8s_job_exists(job, next_attempt)
            if not created:
                continue
            marked = self.repo.mark_job_running(job.id)
            if not marked:
                LOGGER.info(
                    "Skipped mark RUNNING because job state changed",
                    extra={"job_id": str(job.id)},
                )
                continue
            LOGGER.info(
                "Marked job as RUNNING",
                extra={"job_id": str(job.id), "attempt": marked.attempts},
            )

    def _ensure_k8s_job_exists(self, job: Job, attempt: int) -> bool:
        selector = f"job-system/job-id={job.id},job-system/attempt={attempt}"
        existing = self.batch_api.list_namespaced_job(
            namespace=self.namespace, label_selector=selector
        )
        if existing.items:
            return True

        manifest = _build_k8s_job_manifest(job, self.namespace, attempt)
        try:
            created = self.batch_api.create_namespaced_job(
                namespace=self.namespace, body=manifest
            )
            LOGGER.info(
                "Created Kubernetes Job for workload",
                extra={
                    "job_id": str(job.id),
                    "k8s_job_name": created.metadata.name,
                    "attempt": attempt,
                },
            )
            return True
        except ApiException as exc:
            if exc.status == 409:
                # Safe on restart/race: job already exists for this attempt.
                return True
            LOGGER.exception(
                "Failed to create Kubernetes Job", extra={"job_id": str(job.id)}
            )
            self.repo.update_job_status(
                job.id, "FAILED", error=f"k8s job create failed: {exc.reason}"
            )
            return False

    def _reconcile_running_jobs(self) -> None:
        running_jobs = self.repo.list_jobs(
            status="RUNNING", limit=self.running_scan_limit
        )
        for job in running_jobs:
            k8s_job = self._get_k8s_job_for_job_id(job.id, job.attempts)
            if self._is_timed_out(job):
                self._handle_timeout(job, k8s_job)
                continue
            if not k8s_job:
                self.repo.mark_job_terminal(
                    job.id, "FAILED", error="k8s job missing for running state"
                )
                LOGGER.warning(
                    "Marked RUNNING job as FAILED because backing Kubernetes Job was missing",
                    extra={"job_id": str(job.id), "attempt": job.attempts},
                )
                continue

            k8s_status = k8s_job.status
            if k8s_status and (k8s_status.succeeded or 0) > 0:
                self.repo.mark_job_terminal(job.id, "SUCCEEDED")
                LOGGER.info("Marked job as SUCCEEDED", extra={"job_id": str(job.id)})
                continue

            if k8s_status and (k8s_status.failed or 0) > 0:
                error = self._extract_failure_reason(k8s_status)
                if job.attempts < job.max_retries:
                    next_retry_at = compute_next_retry_at(
                        attempts_completed=job.attempts,
                        backoff_seconds=job.backoff_seconds,
                    )
                    self.repo.mark_job_for_retry(
                        job.id,
                        error=error,
                        next_retry_at=next_retry_at,
                    )
                    LOGGER.info(
                        "Requeued failed job for retry",
                        extra={
                            "job_id": str(job.id),
                            "attempt": job.attempts,
                            "max_retries": job.max_retries,
                            "next_retry_at": next_retry_at.isoformat(),
                        },
                    )
                else:
                    self.repo.mark_job_terminal(job.id, "FAILED", error=error)
                    LOGGER.info(
                        "Marked job as FAILED",
                        extra={"job_id": str(job.id), "error": error},
                    )

    def _get_k8s_job_for_job_id(
        self, job_id: UUID, attempt: int
    ) -> client.V1Job | None:
        selector = f"job-system/job-id={job_id},job-system/attempt={attempt}"
        jobs = self.batch_api.list_namespaced_job(
            namespace=self.namespace, label_selector=selector
        )
        if not jobs.items:
            return None
        jobs.items.sort(key=lambda item: item.metadata.creation_timestamp, reverse=True)
        return jobs.items[0]

    @staticmethod
    def _extract_failure_reason(status: client.V1JobStatus) -> str:
        conditions = status.conditions or []
        for condition in conditions:
            if condition.type == "Failed":
                return condition.message or condition.reason or "Job failed"
        return "Job failed"

    @staticmethod
    def _is_timed_out(job: Job) -> bool:
        if not job.timeout_seconds or not job.started_at:
            return False
        now = datetime.now(timezone.utc)
        return now >= (job.started_at + timedelta(seconds=job.timeout_seconds))

    def _handle_timeout(self, job: Job, k8s_job: client.V1Job | None) -> None:
        if k8s_job:
            try:
                self.batch_api.delete_namespaced_job(
                    name=k8s_job.metadata.name,
                    namespace=self.namespace,
                    propagation_policy="Background",
                )
            except ApiException:
                LOGGER.exception(
                    "Failed deleting timed-out Kubernetes Job",
                    extra={"job_id": str(job.id), "attempt": job.attempts},
                )
        self.repo.mark_job_terminal(job.id, "FAILED", error="timeout")
        LOGGER.warning(
            "Marked job as FAILED due to timeout",
            extra={"job_id": str(job.id), "attempt": job.attempts},
        )


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    Scheduler().run_forever()


if __name__ == "__main__":
    main()
