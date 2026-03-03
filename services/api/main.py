"""FastAPI service for Phase 3 M3.2 job submission and retrieval."""

from __future__ import annotations

import os
from dataclasses import asdict
from functools import lru_cache
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from pkg.job_system import Job, JobRepository

app = FastAPI(title="distributed-job-system-api")


class JobSpec(BaseModel):
    image: str = Field(min_length=1)
    command: list[str] = Field(default_factory=list)
    args: list[str] = Field(default_factory=list)
    env: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=dict)
    max_retries: int = Field(default=0, ge=0)
    backoff_seconds: int = Field(default=5, ge=0)
    timeout_seconds: int | None = Field(default=None, ge=1)
    queue: str = Field(default="default", min_length=1)
    priority: int = 0
    type: str | None = None
    payload: dict[str, Any] | None = None


class JobSubmitResponse(BaseModel):
    job_id: UUID
    status: str


class JobResponse(BaseModel):
    id: UUID
    idempotency_key: str | None
    queue: str
    image: str
    command: list[str]
    args: list[str]
    env: dict[str, Any] | None
    resources: dict[str, Any] | None
    priority: int
    max_retries: int
    backoff_seconds: int
    timeout_seconds: int | None
    status: str
    attempts: int
    desired_status: str | None
    last_error: str | None
    created_at: str
    queued_at: str | None
    started_at: str | None
    finished_at: str | None
    updated_at: str


class CancelResponse(BaseModel):
    job_id: UUID
    status: str


def _job_to_response(job: Job) -> JobResponse:
    raw = asdict(job)
    for key in ("created_at", "queued_at", "started_at", "finished_at", "updated_at"):
        if raw[key] is not None:
            raw[key] = raw[key].isoformat()
    return JobResponse(**raw)


def _job_spec_fingerprint(spec: JobSpec) -> dict[str, Any]:
    # Keep a stable subset for idempotency comparisons.
    return {
        "image": spec.image,
        "command": spec.command,
        "args": spec.args,
        "env": spec.env,
        "resources": spec.resources,
        "max_retries": spec.max_retries,
        "backoff_seconds": spec.backoff_seconds,
        "timeout_seconds": spec.timeout_seconds,
        "queue": spec.queue,
        "priority": spec.priority,
    }


def _job_fingerprint(job: Job) -> dict[str, Any]:
    return {
        "image": job.image,
        "command": job.command,
        "args": job.args,
        "env": job.env or {},
        "resources": job.resources or {},
        "max_retries": job.max_retries,
        "backoff_seconds": job.backoff_seconds,
        "timeout_seconds": job.timeout_seconds,
        "queue": job.queue,
        "priority": job.priority,
    }


@lru_cache
def _repository() -> JobRepository:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    return JobRepository(dsn)


def get_repository() -> JobRepository:
    return _repository()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/jobs", response_model=JobSubmitResponse, status_code=status.HTTP_201_CREATED)
def submit_job(
    spec: JobSpec,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    repo: JobRepository = Depends(get_repository),
) -> JobSubmitResponse:
    if idempotency_key:
        existing = repo.get_job_by_idempotency_key(idempotency_key)
        if existing:
            if _job_fingerprint(existing) != _job_spec_fingerprint(spec):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency-Key conflict: request body differs from existing job",
                )
            return JobSubmitResponse(job_id=existing.id, status=existing.status)

    created = repo.create_job(
        image=spec.image,
        command=spec.command,
        args=spec.args,
        queue=spec.queue,
        env=spec.env,
        resources=spec.resources,
        priority=spec.priority,
        max_retries=spec.max_retries,
        backoff_seconds=spec.backoff_seconds,
        timeout_seconds=spec.timeout_seconds,
        idempotency_key=idempotency_key,
    )
    return JobSubmitResponse(job_id=created.id, status=created.status)


@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: UUID, repo: JobRepository = Depends(get_repository)) -> JobResponse:
    job = repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return _job_to_response(job)


@app.get("/jobs", response_model=list[JobResponse])
def list_jobs(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    repo: JobRepository = Depends(get_repository),
) -> list[JobResponse]:
    jobs = repo.list_jobs(status=status_filter, limit=limit)
    return [_job_to_response(job) for job in jobs]


@app.post("/jobs/{job_id}/cancel", response_model=CancelResponse)
def cancel_job(job_id: UUID, repo: JobRepository = Depends(get_repository)) -> CancelResponse:
    job = repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.status != "QUEUED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only QUEUED jobs can be canceled in M3.2",
        )
    updated = repo.update_job_status(job_id, "CANCELED")
    if not updated:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to cancel job")
    return CancelResponse(job_id=updated.id, status=updated.status)

