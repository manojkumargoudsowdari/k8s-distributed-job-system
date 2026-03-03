"""Prometheus metrics for Phase 3 M3.5 observability."""

from __future__ import annotations

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

JOB_SYSTEM_JOB_LATENCY_SECONDS = Histogram(
    "job_system_job_latency_seconds",
    "Job runtime latency in seconds from started_at to finished_at.",
)

_COUNTER_SYNC_LOCK = Lock()
_LAST_SYNC_TOTALS = {"success_total": 0, "fail_total": 0, "retries_total": 0}


def refresh_gauges_from_db(repo: JobRepository) -> None:
    counts = repo.get_status_counts()
    JOB_SYSTEM_JOBS_QUEUED.set(counts.get("QUEUED", 0))
    JOB_SYSTEM_JOBS_RUNNING.set(counts.get("RUNNING", 0))


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


def render_metrics(repo: JobRepository) -> tuple[bytes, str]:
    refresh_gauges_from_db(repo)
    sync_counters_from_db(repo)
    return generate_latest(), CONTENT_TYPE_LATEST
