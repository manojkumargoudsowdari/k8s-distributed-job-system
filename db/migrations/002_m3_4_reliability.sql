-- 002_m3_4_reliability.sql
-- Phase 3 M3.4: reliability fields for retry/backoff scheduling.

ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;

UPDATE jobs
SET next_retry_at = COALESCE(next_retry_at, queued_at, created_at, now())
WHERE next_retry_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_jobs_dispatch_ready
ON jobs(status, next_retry_at);
