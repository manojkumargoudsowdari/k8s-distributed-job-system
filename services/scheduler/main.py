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
from prometheus_client import start_http_server

from pkg.job_system import (
    Job,
    JobRepository,
    compute_next_retry_at,
    record_dispatch_decision,
    record_quota_block,
    record_retry,
    record_terminal_transition,
    refresh_gauges_from_db,
    sync_counters_from_db,
)

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
        self.dispatch_candidate_multiplier = int(
            os.getenv("SCHEDULER_FAIR_CANDIDATE_MULTIPLIER", "5")
        )
        self.running_scan_limit = int(os.getenv("SCHEDULER_RUNNING_SCAN_LIMIT", "50"))
        self.metrics_port = int(os.getenv("SCHEDULER_METRICS_PORT", "9000"))
        self.tenant_max_running = int(os.getenv("TENANT_MAX_RUNNING", "2"))
        # In-memory RR cursor; deterministic for single-scheduler operation.
        self._rr_last_tenant: str | None = None

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
        start_http_server(self.metrics_port)
        LOGGER.info("scheduler_started metrics_port=%s", self.metrics_port)
        try:
            while True:
                self.reconcile_once()
                time.sleep(self.poll_interval_seconds)
        finally:
            self.repo.close()

    def reconcile_once(self) -> None:
        refresh_gauges_from_db(self.repo)
        sync_counters_from_db(self.repo)
        self._dispatch_queued_jobs()
        self._reconcile_running_jobs()

    def _dispatch_queued_jobs(self) -> None:
        candidate_multiplier = max(
            1, int(getattr(self, "dispatch_candidate_multiplier", 1))
        )
        candidate_limit = max(
            self.dispatch_batch_size, self.dispatch_batch_size * candidate_multiplier
        )
        queued_jobs = self.repo.list_dispatchable_jobs(limit=candidate_limit)
        queued_jobs = self._order_dispatchable_jobs_round_robin(queued_jobs)
        if not queued_jobs:
            record_dispatch_decision(decision="no_candidates")
            LOGGER.info("dispatch_no_candidates")
            return
        running_by_tenant: dict[str, int] = {}
        dispatched = 0
        for job in queued_jobs:
            if dispatched >= self.dispatch_batch_size:
                break
            running_count = running_by_tenant.get(job.tenant_id)
            if running_count is None:
                running_count = self.repo.count_running_jobs_by_tenant(job.tenant_id)
                running_by_tenant[job.tenant_id] = running_count

            if running_count >= self.tenant_max_running:
                LOGGER.info(
                    "dispatch_skipped_tenant_quota tenant_id=%s running=%s limit=%s job_id=%s",
                    job.tenant_id,
                    running_count,
                    self.tenant_max_running,
                    job.id,
                )
                record_quota_block(job.tenant_id)
                record_dispatch_decision(
                    decision="quota_skipped",
                    tenant_id=job.tenant_id,
                )
                continue

            next_attempt = job.attempts + 1
            created = self._ensure_k8s_job_exists(job, next_attempt)
            if not created:
                continue
            marked = self.repo.mark_job_running(job.id)
            if not marked:
                LOGGER.info("dispatch_skip_state_changed job_id=%s", job.id)
                continue
            running_by_tenant[job.tenant_id] = running_count + 1
            self._rr_last_tenant = marked.tenant_id
            dispatched += 1
            record_dispatch_decision(decision="dispatched", tenant_id=marked.tenant_id)
            LOGGER.info(
                "job_running tenant_id=%s job_id=%s attempt=%s",
                marked.tenant_id,
                marked.id,
                marked.attempts,
            )

    def _order_dispatchable_jobs_round_robin(self, jobs: list[Job]) -> list[Job]:
        if not jobs:
            return []

        groups: dict[str, list[Job]] = {}
        tenant_order: list[str] = []
        for job in jobs:
            if job.tenant_id not in groups:
                groups[job.tenant_id] = []
                tenant_order.append(job.tenant_id)
            groups[job.tenant_id].append(job)

        cursor = getattr(self, "_rr_last_tenant", None)
        if cursor in tenant_order:
            idx = tenant_order.index(cursor)
            tenant_order = tenant_order[idx + 1 :] + tenant_order[: idx + 1]

        ordered: list[Job] = []
        pending = True
        while pending:
            pending = False
            for tenant in tenant_order:
                bucket = groups[tenant]
                if bucket:
                    ordered.append(bucket.pop(0))
                    pending = True
        return ordered

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
                "k8s_job_created job_id=%s k8s_job_name=%s attempt=%s",
                job.id,
                created.metadata.name,
                attempt,
            )
            return True
        except ApiException as exc:
            if exc.status == 409:
                # Safe on restart/race: job already exists for this attempt.
                return True
            LOGGER.exception("k8s_job_create_failed job_id=%s", job.id)
            terminal = self.repo.update_job_status(
                job.id, "FAILED", error=f"k8s job create failed: {exc.reason}"
            )
            if terminal:
                record_terminal_transition(terminal, "FAILED")
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
                terminal = self.repo.mark_job_terminal(
                    job.id, "FAILED", error="k8s job missing for running state"
                )
                if terminal:
                    record_terminal_transition(terminal, "FAILED")
                LOGGER.warning(
                    "missing_k8s_job_failed job_id=%s attempt=%s",
                    job.id,
                    job.attempts,
                )
                continue

            k8s_status = k8s_job.status
            if k8s_status and (k8s_status.succeeded or 0) > 0:
                terminal = self.repo.mark_job_terminal(job.id, "SUCCEEDED")
                if terminal:
                    record_terminal_transition(terminal, "SUCCEEDED")
                LOGGER.info("job_succeeded job_id=%s", job.id)
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
                    record_retry()
                    LOGGER.info(
                        "job_requeued_for_retry job_id=%s attempt=%s max_retries=%s next_retry_at=%s",
                        job.id,
                        job.attempts,
                        job.max_retries,
                        next_retry_at.isoformat(),
                    )
                else:
                    terminal = self.repo.mark_job_terminal(
                        job.id, "FAILED", error=error
                    )
                    if terminal:
                        record_terminal_transition(terminal, "FAILED")
                    LOGGER.info(
                        "job_failed job_id=%s error=%s",
                        job.id,
                        error,
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
                    "timeout_delete_failed job_id=%s attempt=%s",
                    job.id,
                    job.attempts,
                )
        terminal = self.repo.mark_job_terminal(job.id, "FAILED", error="timeout")
        if terminal:
            record_terminal_transition(terminal, "FAILED")
        LOGGER.warning(
            "job_timeout_failed job_id=%s attempt=%s",
            job.id,
            job.attempts,
        )


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    Scheduler().run_forever()


if __name__ == "__main__":
    main()
