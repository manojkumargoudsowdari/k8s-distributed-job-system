-- 003_m4_1_tenant_identity.sql
-- Phase 4 M4.1: tenant identity and tenant-aware scheduler indexes.

ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS tenant_id TEXT;

UPDATE jobs
SET tenant_id = 'tenant_default'
WHERE tenant_id IS NULL;

ALTER TABLE jobs
ALTER COLUMN tenant_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_jobs_tenant_status
ON jobs(tenant_id, status);

CREATE INDEX IF NOT EXISTS idx_jobs_tenant_status_created
ON jobs(tenant_id, status, created_at);
