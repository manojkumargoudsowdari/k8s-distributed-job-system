"""Database access layer for distributed job system core (M3.1)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from pkg.job_system.models import Job


class JobRepository:
    def __init__(self, dsn: str) -> None:
        self.pool = ConnectionPool(conninfo=dsn, kwargs={"row_factory": dict_row})

    def close(self) -> None:
        self.pool.close()

    def create_job(
        self,
        *,
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
        job_id = uuid4()
        now = datetime.now(timezone.utc)
        command = command or []
        args = args or []
        env = env or {}
        resources = resources or {}

        query = """
        INSERT INTO jobs (
            id, idempotency_key, queue, image, command, args, env, resources,
            priority, max_retries, backoff_seconds, timeout_seconds, status, created_at, queued_at, updated_at
        )
        VALUES (
            %(id)s, %(idempotency_key)s, %(queue)s, %(image)s, %(command)s, %(args)s,
            %(env)s, %(resources)s, %(priority)s, %(max_retries)s,
            %(backoff_seconds)s, %(timeout_seconds)s,
            'QUEUED', %(created_at)s, %(queued_at)s, %(updated_at)s
        )
        RETURNING *
        """
        params = {
            "id": job_id,
            "idempotency_key": idempotency_key,
            "queue": queue,
            "image": image,
            "command": command,
            "args": args,
            "env": Jsonb(env),
            "resources": Jsonb(resources),
            "priority": priority,
            "max_retries": max_retries,
            "backoff_seconds": backoff_seconds,
            "timeout_seconds": timeout_seconds,
            "created_at": now,
            "queued_at": now,
            "updated_at": now,
        }
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            conn.commit()
        return _row_to_job(row)

    def get_job(self, job_id: UUID) -> Job | None:
        query = "SELECT * FROM jobs WHERE id = %(id)s"
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(query, {"id": job_id})
            row = cur.fetchone()
        return _row_to_job(row) if row else None

    def get_job_by_idempotency_key(self, idempotency_key: str) -> Job | None:
        query = "SELECT * FROM jobs WHERE idempotency_key = %(idempotency_key)s"
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(query, {"idempotency_key": idempotency_key})
            row = cur.fetchone()
        return _row_to_job(row) if row else None

    def list_jobs(self, status: str | None = None, limit: int = 50) -> list[Job]:
        if status:
            query = "SELECT * FROM jobs WHERE status = %(status)s ORDER BY created_at DESC LIMIT %(limit)s"
            params = {"status": status, "limit": limit}
        else:
            query = "SELECT * FROM jobs ORDER BY created_at DESC LIMIT %(limit)s"
            params = {"limit": limit}

        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [_row_to_job(row) for row in rows]

    def update_job_status(self, job_id: UUID, status: str, error: str | None = None) -> Job | None:
        now = datetime.now(timezone.utc)
        query = """
        UPDATE jobs
        SET status = %(status)s,
            last_error = %(error)s,
            updated_at = %(updated_at)s,
            started_at = CASE WHEN %(status)s = 'RUNNING' AND started_at IS NULL THEN %(updated_at)s ELSE started_at END,
            finished_at = CASE WHEN %(status)s IN ('SUCCEEDED', 'FAILED', 'CANCELED') THEN %(updated_at)s ELSE finished_at END
        WHERE id = %(id)s
        RETURNING *
        """
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(query, {"id": job_id, "status": status, "error": error, "updated_at": now})
            row = cur.fetchone()
            conn.commit()
        return _row_to_job(row) if row else None


def _row_to_job(row: dict[str, Any]) -> Job:
    return Job(
        id=row["id"],
        idempotency_key=row.get("idempotency_key"),
        queue=row["queue"],
        image=row["image"],
        command=row["command"],
        args=row["args"],
        env=row.get("env"),
        resources=row.get("resources"),
        priority=row["priority"],
        max_retries=row["max_retries"],
        backoff_seconds=row["backoff_seconds"],
        timeout_seconds=row.get("timeout_seconds"),
        status=row["status"],
        attempts=row["attempts"],
        desired_status=row.get("desired_status"),
        last_error=row.get("last_error"),
        created_at=row["created_at"],
        queued_at=row.get("queued_at"),
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
        updated_at=row["updated_at"],
    )
