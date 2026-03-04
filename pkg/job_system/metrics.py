"""Prometheus metrics for Phase 3 M3.5 observability."""

from __future__ import annotations

import hashlib
from threading import Lock

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from pkg.job_system.db import JobRepository
from pkg.job_system.models import Job

JOB_SYSTEM_JOBS_QUEUED = Gauge(
    "job_system_jobs_queued",
    "Number of queued jobs ready or waiting for retry.",
)
JOB_SYSTEM_JOBS_RUNNING = Gauge(
    "job_system_jobs_running",
    "Number of currently running jobs.",
)
JOB_SYSTEM_JOBS_QUEUED_BY_TENANT_BUCKET = Gauge(
    "job_system_jobs_queued_by_tenant_bucket",
    "Number of queued jobs grouped by hashed tenant bucket.",
    ["tenant_bucket"],
)
JOB_SYSTEM_JOBS_RUNNING_BY_TENANT_BUCKET = Gauge(
    "job_system_jobs_running_by_tenant_bucket",
    "Number of running jobs grouped by hashed tenant bucket.",
    ["tenant_bucket"],
)

JOB_SYSTEM_JOB_SUCCESS_TOTAL = Counter(
    "job_system_job_success_total",
    "Total number of succeeded jobs.",
)
JOB_SYSTEM_JOB_FAIL_TOTAL = Counter(
    "job_system_job_fail_total",
    "Total number of failed jobs.",
)
JOB_SYSTEM_JOB_RETRIES_TOTAL = Counter(
    "job_system_job_retries_total",
    "Total number of retry requeues.",
)
JOB_SYSTEM_SCHEDULER_DISPATCH_DECISIONS_TOTAL = Counter(
    "job_system_scheduler_dispatch_decisions_total",
    "Total scheduler dispatch decisions by decision type.",
    ["decision"],
)
JOB_SYSTEM_SCHEDULER_DISPATCH_DECISIONS_BY_TENANT_BUCKET_TOTAL = Counter(
    "job_system_scheduler_dispatch_decisions_by_tenant_bucket_total",
    "Scheduler dispatch decisions grouped by hashed tenant bucket.",
    ["decision", "tenant_bucket"],
)
JOB_SYSTEM_SCHEDULER_QUOTA_BLOCKS_TOTAL = Counter(
    "job_system_scheduler_quota_blocks_total",
    "Total number of scheduler dispatch skips due to tenant quota.",
)
JOB_SYSTEM_SCHEDULER_QUOTA_BLOCKS_BY_TENANT_BUCKET_TOTAL = Counter(
    "job_system_scheduler_quota_blocks_by_tenant_bucket_total",
    "Scheduler quota blocks grouped by hashed tenant bucket.",
    ["tenant_bucket"],
)
JOB_SYSTEM_API_SUBMIT_RATE_LIMITED_TOTAL = Counter(
    "job_system_api_submit_rate_limited_total",
    "Total submit requests rejected by API rate limiter.",
)
JOB_SYSTEM_API_SUBMIT_RATE_LIMITED_BY_TENANT_BUCKET_TOTAL = Counter(
    "job_system_api_submit_rate_limited_by_tenant_bucket_total",
    "Submit requests rejected by API rate limiter grouped by hashed tenant bucket.",
    ["tenant_bucket"],
)

JOB_SYSTEM_JOB_LATENCY_SECONDS = Histogram(
    "job_system_job_latency_seconds",
    "Job runtime latency in seconds from started_at to finished_at.",
)

_COUNTER_SYNC_LOCK = Lock()
_LAST_SYNC_TOTALS = {"success_total": 0, "fail_total": 0, "retries_total": 0}
TENANT_BUCKETS = tuple(f"{idx:x}" for idx in range(16))
DISPATCH_DECISIONS = ("dispatched", "quota_skipped", "no_candidates")


def tenant_bucket(tenant_id: str) -> str:
    digest = hashlib.md5(tenant_id.encode("utf-8"), usedforsecurity=False).hexdigest()
    return digest[0]


def refresh_gauges_from_db(repo: JobRepository) -> None:
    counts = repo.get_status_counts()
    JOB_SYSTEM_JOBS_QUEUED.set(counts.get("QUEUED", 0))
    JOB_SYSTEM_JOBS_RUNNING.set(counts.get("RUNNING", 0))
    for bucket in TENANT_BUCKETS:
        JOB_SYSTEM_JOBS_QUEUED_BY_TENANT_BUCKET.labels(tenant_bucket=bucket).set(0)
        JOB_SYSTEM_JOBS_RUNNING_BY_TENANT_BUCKET.labels(tenant_bucket=bucket).set(0)

    if hasattr(repo, "get_status_counts_by_tenant_status"):
        rows = repo.get_status_counts_by_tenant_status()
        queued_by_bucket = {bucket: 0 for bucket in TENANT_BUCKETS}
        running_by_bucket = {bucket: 0 for bucket in TENANT_BUCKETS}
        for row in rows:
            bucket = tenant_bucket(row["tenant_id"])
            if row["status"] == "QUEUED":
                queued_by_bucket[bucket] += int(row["count"])
            if row["status"] == "RUNNING":
                running_by_bucket[bucket] += int(row["count"])

        for bucket in TENANT_BUCKETS:
            JOB_SYSTEM_JOBS_QUEUED_BY_TENANT_BUCKET.labels(tenant_bucket=bucket).set(
                queued_by_bucket[bucket]
            )
            JOB_SYSTEM_JOBS_RUNNING_BY_TENANT_BUCKET.labels(tenant_bucket=bucket).set(
                running_by_bucket[bucket]
            )


def sync_counters_from_db(repo: JobRepository) -> None:
    totals = repo.get_reliability_totals()
    with _COUNTER_SYNC_LOCK:
        for key, metric in (
            ("success_total", JOB_SYSTEM_JOB_SUCCESS_TOTAL),
            ("fail_total", JOB_SYSTEM_JOB_FAIL_TOTAL),
            ("retries_total", JOB_SYSTEM_JOB_RETRIES_TOTAL),
        ):
            delta = totals[key] - _LAST_SYNC_TOTALS[key]
            if delta > 0:
                metric.inc(delta)
            _LAST_SYNC_TOTALS[key] = totals[key]


def record_retry() -> None:
    JOB_SYSTEM_JOB_RETRIES_TOTAL.inc()


def record_terminal_transition(job: Job, terminal_status: str) -> None:
    if terminal_status == "SUCCEEDED":
        JOB_SYSTEM_JOB_SUCCESS_TOTAL.inc()
    elif terminal_status == "FAILED":
        JOB_SYSTEM_JOB_FAIL_TOTAL.inc()

    if job.started_at and job.finished_at:
        latency = (job.finished_at - job.started_at).total_seconds()
        if latency >= 0:
            JOB_SYSTEM_JOB_LATENCY_SECONDS.observe(latency)


def record_dispatch_decision(*, decision: str, tenant_id: str | None = None) -> None:
    JOB_SYSTEM_SCHEDULER_DISPATCH_DECISIONS_TOTAL.labels(decision=decision).inc()
    if tenant_id:
        JOB_SYSTEM_SCHEDULER_DISPATCH_DECISIONS_BY_TENANT_BUCKET_TOTAL.labels(
            decision=decision,
            tenant_bucket=tenant_bucket(tenant_id),
        ).inc()


def record_quota_block(tenant_id: str) -> None:
    JOB_SYSTEM_SCHEDULER_QUOTA_BLOCKS_TOTAL.inc()
    JOB_SYSTEM_SCHEDULER_QUOTA_BLOCKS_BY_TENANT_BUCKET_TOTAL.labels(
        tenant_bucket=tenant_bucket(tenant_id)
    ).inc()


def record_api_rate_limited(tenant_id: str) -> None:
    JOB_SYSTEM_API_SUBMIT_RATE_LIMITED_TOTAL.inc()
    JOB_SYSTEM_API_SUBMIT_RATE_LIMITED_BY_TENANT_BUCKET_TOTAL.labels(
        tenant_bucket=tenant_bucket(tenant_id)
    ).inc()


def _initialize_labeled_metrics() -> None:
    for bucket in TENANT_BUCKETS:
        JOB_SYSTEM_JOBS_QUEUED_BY_TENANT_BUCKET.labels(tenant_bucket=bucket).set(0)
        JOB_SYSTEM_JOBS_RUNNING_BY_TENANT_BUCKET.labels(tenant_bucket=bucket).set(0)
        JOB_SYSTEM_SCHEDULER_QUOTA_BLOCKS_BY_TENANT_BUCKET_TOTAL.labels(
            tenant_bucket=bucket
        )
        JOB_SYSTEM_API_SUBMIT_RATE_LIMITED_BY_TENANT_BUCKET_TOTAL.labels(
            tenant_bucket=bucket
        )
        for decision in DISPATCH_DECISIONS:
            JOB_SYSTEM_SCHEDULER_DISPATCH_DECISIONS_BY_TENANT_BUCKET_TOTAL.labels(
                decision=decision,
                tenant_bucket=bucket,
            )
    for decision in DISPATCH_DECISIONS:
        JOB_SYSTEM_SCHEDULER_DISPATCH_DECISIONS_TOTAL.labels(decision=decision)


_initialize_labeled_metrics()


def render_metrics(repo: JobRepository) -> tuple[bytes, str]:
    refresh_gauges_from_db(repo)
    sync_counters_from_db(repo)
    return generate_latest(), CONTENT_TYPE_LATEST
