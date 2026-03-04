-- 004_m4_3_tenant_scope_audit.sql
-- Phase 4 M4.3: audit metadata for submitted jobs.

ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS submitted_by TEXT;

ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS request_id TEXT;

ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS created_from_ip TEXT;
