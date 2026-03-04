"""Domain models for the distributed job system core (M3.1)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass
class Job:
    id: UUID
    tenant_id: str
    image: str
    command: list[str]
    args: list[str]
    queue: str
    status: str
    attempts: int
    priority: int
    max_retries: int
    backoff_seconds: int
    timeout_seconds: int | None
    created_at: datetime
    updated_at: datetime
    idempotency_key: str | None = None
    env: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    desired_status: str | None = None
    last_error: str | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    next_retry_at: datetime | None = None


@dataclass
class JobAttempt:
    id: int
    job_id: UUID
    attempt_number: int
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    exit_code: int | None = None
    error_message: str | None = None
