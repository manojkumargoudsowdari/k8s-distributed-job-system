"""Database access layer for distributed job system core (M3.1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from psycopg.errors import UniqueViolation
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
            priority, max_retries, backoff_seconds, timeout_seconds, status, created_at, queued_at, next_retry_at, updated_at
        )
        VALUES (
            %(id)s, %(idempotency_key)s, %(queue)s, %(image)s, %(command)s, %(args)s,
            %(env)s, %(resources)s, %(priority)s, %(max_retries)s,
            %(backoff_seconds)s, %(timeout_seconds)s,
            'QUEUED', %(created_at)s, %(queued_at)s, %(next_retry_at)s, %(updated_at)s
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
            "next_retry_at": now,
            "updated_at": now,
        }
        with self.pool.connection() as conn, conn.cursor() as cur:
            try:
                cur.execute(query, params)
                row = cur.fetchone()
                conn.commit()
            except UniqueViolation:
                conn.rollback()
                if not idempotency_key:
                    raise
                existing = self.get_job_by_idempotency_key(idempotency_key)
                if existing:
                    return existing
                raise
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

    def list_dispatchable_jobs(self, limit: int = 5) -> list[Job]:
        now = datetime.now(timezone.utc)
        query = """
        SELECT *
        FROM jobs
        WHERE status = 'QUEUED'
          AND COALESCE(next_retry_at, queued_at, created_at) <= %(now)s
        ORDER BY priority DESC, COALESCE(next_retry_at, queued_at, created_at) ASC, created_at ASC
        LIMIT %(limit)s
        """
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(query, {"now": now, "limit": limit})
            rows = cur.fetchall()
        return [_row_to_job(row) for row in rows]

    def get_status_counts(self) -> dict[str, int]:
        query = """
        SELECT status, COUNT(*) AS count
        FROM jobs
        GROUP BY status
        """
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["status"]] = int(row["count"])
        return counts

    def get_reliability_totals(self) -> dict[str, int]:
        query = """
        SELECT
            COUNT(*) FILTER (WHERE status = 'SUCCEEDED') AS success_total,
            COUNT(*) FILTER (WHERE status = 'FAILED') AS fail_total,
            COALESCE(SUM(GREATEST(attempts - 1, 0)), 0) AS retries_total
        FROM jobs
        """
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(query)
            row = cur.fetchone()
        return {
            "success_total": int(row["success_total"]),
            "fail_total": int(row["fail_total"]),
            "retries_total": int(row["retries_total"]),
        }

    def mark_job_running(self, job_id: UUID) -> Job | None:
        now = datetime.now(timezone.utc)
        query = """
        UPDATE jobs
        SET status = 'RUNNING',
            updated_at = %(updated_at)s,
            started_at = %(updated_at)s,
            finished_at = NULL,
            attempts = attempts + 1
        WHERE id = %(id)s AND status = 'QUEUED'
        RETURNING *
        """
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(query, {"id": job_id, "updated_at": now})
            row = cur.fetchone()
            conn.commit()
        return _row_to_job(row) if row else None

    def mark_job_for_retry(
        self, job_id: UUID, *, error: str, next_retry_at: datetime
    ) -> Job | None:
        now = datetime.now(timezone.utc)
        query = """
        UPDATE jobs
        SET status = 'QUEUED',
            last_error = %(error)s,
            queued_at = %(queued_at)s,
            next_retry_at = %(next_retry_at)s,
            updated_at = %(updated_at)s
        WHERE id = %(id)s AND status = 'RUNNING'
        RETURNING *
        """
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                query,
                {
                    "id": job_id,
                    "error": error,
                    "queued_at": now,
                    "next_retry_at": next_retry_at,
                    "updated_at": now,
                },
            )
            row = cur.fetchone()
            conn.commit()
        return _row_to_job(row) if row else None

    def mark_job_terminal(
        self, job_id: UUID, status: str, error: str | None = None
    ) -> Job | None:
        now = datetime.now(timezone.utc)
        query = """
        UPDATE jobs
        SET status = %(status)s,
            last_error = %(error)s,
            updated_at = %(updated_at)s,
            next_retry_at = NULL,
            finished_at = COALESCE(finished_at, %(updated_at)s)
        WHERE id = %(id)s AND status = 'RUNNING'
        RETURNING *
        """
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                query,
                {"id": job_id, "status": status, "error": error, "updated_at": now},
            )
            row = cur.fetchone()
            conn.commit()
        return _row_to_job(row) if row else None

    def update_job_status(
        self, job_id: UUID, status: str, error: str | None = None
    ) -> Job | None:
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
            cur.execute(
                query,
                {"id": job_id, "status": status, "error": error, "updated_at": now},
            )
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
        next_retry_at=row.get("next_retry_at"),
        updated_at=row["updated_at"],
    )


def compute_next_retry_at(*, attempts_completed: int, backoff_seconds: int) -> datetime:
    """Return next retry timestamp using triangular-number backoff.

    Delay sequence with backoff_seconds=5:
    attempts_completed=1 -> 5s
    attempts_completed=2 -> 15s
    attempts_completed=3 -> 30s
    """
    delay_seconds = backoff_seconds * attempts_completed * (attempts_completed + 1) // 2
    return datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
