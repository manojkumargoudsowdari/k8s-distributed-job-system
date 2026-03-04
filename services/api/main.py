"""FastAPI service for Phase 3 M3.2 job submission and retrieval."""

from __future__ import annotations

import os
import logging
import re
import math
import time
from threading import Lock
from dataclasses import asdict
from functools import lru_cache
from typing import Any
from uuid import UUID

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, Field

from pkg.job_system import Job, JobRepository, record_api_rate_limited, render_metrics

app = FastAPI(title="distributed-job-system-api")
# Reuse uvicorn logger pipeline so app logs appear in pod logs.
LOGGER = logging.getLogger("uvicorn.error")
TENANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DEFAULT_TENANT_SUBMIT_RPS = 2.0
DEFAULT_TENANT_SUBMIT_BURST = 5
DEFAULT_MAX_PAYLOAD_BYTES = 16384
DEFAULT_MAX_ENV_VARS = 64
DEFAULT_MAX_ENV_KEY_LENGTH = 128
DEFAULT_MAX_ENV_VALUE_LENGTH = 2048
DEFAULT_MAX_RETRIES = 10
DEFAULT_MAX_TIMEOUT_SECONDS = 86400


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
    tenant_id: str
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
    next_retry_at: str | None
    updated_at: str


class CancelResponse(BaseModel):
    job_id: UUID
    status: str


class TenantRateLimiter:
    """In-memory token bucket keyed by tenant."""

    def __init__(self, rps: float, burst: int) -> None:
        self.rps = max(rps, 0.001)
        self.burst = max(burst, 1)
        self._lock = Lock()
        self._state: dict[str, tuple[float, float]] = {}

    def allow(self, tenant_id: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._state.get(tenant_id, (float(self.burst), now))
            elapsed = max(0.0, now - last)
            tokens = min(float(self.burst), tokens + elapsed * self.rps)
            if tokens >= 1.0:
                tokens -= 1.0
                self._state[tenant_id] = (tokens, now)
                return True, 0

            needed = 1.0 - tokens
            retry_after = max(1, int(math.ceil(needed / self.rps)))
            self._state[tenant_id] = (tokens, now)
            return False, retry_after


def _job_to_response(job: Job) -> JobResponse:
    raw = asdict(job)
    for key in (
        "created_at",
        "queued_at",
        "started_at",
        "finished_at",
        "next_retry_at",
        "updated_at",
    ):
        if raw[key] is not None:
            raw[key] = raw[key].isoformat()
    return JobResponse(**raw)


def _job_spec_fingerprint(spec: JobSpec, tenant_id: str) -> dict[str, Any]:
    # Keep a stable subset for idempotency comparisons.
    return {
        "tenant_id": tenant_id,
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
        "tenant_id": job.tenant_id,
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


def _validated_tenant_id(
    tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
) -> str:
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-Id header is required",
        )
    if not TENANT_ID_PATTERN.fullmatch(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-Id must match ^[A-Za-z0-9_-]{1,64}$",
        )
    return tenant_id


@lru_cache
def _repository() -> JobRepository:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    return JobRepository(dsn)


def get_repository() -> JobRepository:
    return _repository()


@lru_cache
def get_submit_limiter() -> TenantRateLimiter:
    rps = float(os.getenv("TENANT_SUBMIT_RPS", str(DEFAULT_TENANT_SUBMIT_RPS)))
    burst = int(os.getenv("TENANT_SUBMIT_BURST", str(DEFAULT_TENANT_SUBMIT_BURST)))
    return TenantRateLimiter(rps=rps, burst=burst)


def _validate_submit_caps(spec: JobSpec) -> None:
    payload_bytes = len(spec.model_dump_json().encode("utf-8"))
    max_payload_bytes = int(
        os.getenv("JOB_SUBMIT_MAX_PAYLOAD_BYTES", str(DEFAULT_MAX_PAYLOAD_BYTES))
    )
    if payload_bytes > max_payload_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job payload exceeds JOB_SUBMIT_MAX_PAYLOAD_BYTES ({max_payload_bytes})",
        )

    max_env_vars = int(os.getenv("JOB_SUBMIT_MAX_ENV_VARS", str(DEFAULT_MAX_ENV_VARS)))
    if len(spec.env) > max_env_vars:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"env exceeds JOB_SUBMIT_MAX_ENV_VARS ({max_env_vars})",
        )

    max_env_key_length = int(
        os.getenv("JOB_SUBMIT_MAX_ENV_KEY_LENGTH", str(DEFAULT_MAX_ENV_KEY_LENGTH))
    )
    max_env_value_length = int(
        os.getenv("JOB_SUBMIT_MAX_ENV_VALUE_LENGTH", str(DEFAULT_MAX_ENV_VALUE_LENGTH))
    )
    for key, value in spec.env.items():
        if len(str(key)) > max_env_key_length:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"env key exceeds JOB_SUBMIT_MAX_ENV_KEY_LENGTH ({max_env_key_length})",
            )
        if len(str(value)) > max_env_value_length:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"env value exceeds JOB_SUBMIT_MAX_ENV_VALUE_LENGTH ({max_env_value_length})",
            )

    max_retries_cap = int(
        os.getenv("JOB_SUBMIT_MAX_RETRIES", str(DEFAULT_MAX_RETRIES))
    )
    if spec.max_retries > max_retries_cap:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"max_retries exceeds JOB_SUBMIT_MAX_RETRIES ({max_retries_cap})",
        )

    max_timeout_seconds_cap = int(
        os.getenv("JOB_SUBMIT_MAX_TIMEOUT_SECONDS", str(DEFAULT_MAX_TIMEOUT_SECONDS))
    )
    if (
        spec.timeout_seconds is not None
        and spec.timeout_seconds > max_timeout_seconds_cap
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"timeout_seconds exceeds JOB_SUBMIT_MAX_TIMEOUT_SECONDS ({max_timeout_seconds_cap})",
        )


@app.on_event("shutdown")
def shutdown_event() -> None:
    if _repository.cache_info().currsize > 0:
        _repository().close()
        _repository.cache_clear()
    get_submit_limiter.cache_clear()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics(repo: JobRepository = Depends(get_repository)) -> Response:
    body, content_type = render_metrics(repo)
    return Response(content=body, media_type=content_type)


@app.post(
    "/jobs", response_model=JobSubmitResponse, status_code=status.HTTP_201_CREATED
)
def submit_job(
    request: Request,
    spec: JobSpec,
    tenant_id: str = Depends(_validated_tenant_id),
    limiter: TenantRateLimiter = Depends(get_submit_limiter),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    submitted_by: str | None = Header(default=None, alias="X-Submitted-By"),
    request_id: str | None = Header(default=None, alias="X-Request-Id"),
    repo: JobRepository = Depends(get_repository),
) -> JobSubmitResponse:
    _validate_submit_caps(spec)
    allowed, retry_after = limiter.allow(tenant_id)
    if not allowed:
        record_api_rate_limited(tenant_id)
        LOGGER.warning(
            "submit_rate_limited tenant_id=%s retry_after=%s",
            tenant_id,
            retry_after,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Tenant submit rate limit exceeded; retry later",
            headers={"Retry-After": str(retry_after)},
        )

    if idempotency_key:
        existing = repo.get_job_by_idempotency_key(idempotency_key)
        if existing:
            if existing.tenant_id != tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency-Key conflict: key already used by a different tenant",
                )
            if _job_fingerprint(existing) != _job_spec_fingerprint(spec, tenant_id):
                LOGGER.warning(
                    "idempotency_conflict idempotency_key=%s", idempotency_key
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency-Key conflict: request body differs from existing job",
                )
            LOGGER.info(
                "submit_idempotent_hit tenant_id=%s job_id=%s status=%s",
                tenant_id,
                existing.id,
                existing.status,
            )
            return JobSubmitResponse(job_id=existing.id, status=existing.status)

    created = repo.create_job(
        tenant_id=tenant_id,
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
        submitted_by=submitted_by,
        request_id=request_id,
        created_from_ip=request.client.host if request.client else None,
    )
    if idempotency_key and _job_fingerprint(created) != _job_spec_fingerprint(
        spec, tenant_id
    ):
        LOGGER.warning(
            "idempotency_conflict_post_create job_id=%s idempotency_key=%s",
            created.id,
            idempotency_key,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency-Key conflict: request body differs from existing job",
        )
    LOGGER.info(
        "submit_created tenant_id=%s job_id=%s status=%s",
        tenant_id,
        created.id,
        created.status,
    )
    return JobSubmitResponse(job_id=created.id, status=created.status)


@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: UUID,
    tenant_id: str = Depends(_validated_tenant_id),
    repo: JobRepository = Depends(get_repository),
) -> JobResponse:
    job = repo.get_job_for_tenant(tenant_id, job_id)
    if not job:
        LOGGER.warning("get_not_found tenant_id=%s job_id=%s", tenant_id, job_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )
    LOGGER.info(
        "get_job job_id=%s status=%s attempts=%s", job.id, job.status, job.attempts
    )
    return _job_to_response(job)


@app.get("/jobs", response_model=list[JobResponse])
def list_jobs(
    tenant_id: str = Depends(_validated_tenant_id),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    repo: JobRepository = Depends(get_repository),
) -> list[JobResponse]:
    jobs = repo.list_jobs_for_tenant(tenant_id, status=status_filter, limit=limit)
    LOGGER.info(
        "list_jobs tenant_id=%s status=%s limit=%s count=%s",
        tenant_id,
        status_filter,
        limit,
        len(jobs),
    )
    return [_job_to_response(job) for job in jobs]


@app.post("/jobs/{job_id}/cancel", response_model=CancelResponse)
def cancel_job(
    job_id: UUID,
    tenant_id: str = Depends(_validated_tenant_id),
    repo: JobRepository = Depends(get_repository),
) -> CancelResponse:
    job = repo.get_job_for_tenant(tenant_id, job_id)
    if not job:
        LOGGER.warning("cancel_not_found tenant_id=%s job_id=%s", tenant_id, job_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )
    if job.status != "QUEUED":
        LOGGER.warning("cancel_conflict job_id=%s status=%s", job_id, job.status)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only QUEUED jobs can be canceled in M3.2",
        )
    updated = repo.update_job_status_for_tenant(tenant_id, job_id, "CANCELED")
    if not updated:
        LOGGER.error("cancel_failed_update job_id=%s", job_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel job",
        )
    LOGGER.info("cancelled job_id=%s status=%s", updated.id, updated.status)
    return CancelResponse(job_id=updated.id, status=updated.status)
