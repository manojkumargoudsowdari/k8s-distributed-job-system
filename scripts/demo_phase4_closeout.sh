#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

OUT_DIR="${DEMO_OUTPUT_DIR:-docs/evidence/phase4/m4.demo/outputs}"

TENANT_MAX_RUNNING="${TENANT_MAX_RUNNING:-1}"
TENANT_SUBMIT_RPS="${TENANT_SUBMIT_RPS:-1}"
TENANT_SUBMIT_BURST="${TENANT_SUBMIT_BURST:-1}"
SCHEDULER_METRICS_PORT="${SCHEDULER_METRICS_PORT:-9000}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $1" >&2
    exit 1
  fi
}

require_cmd bash
PYTHON_BIN=""
for candidate in \
  "python" \
  "python3" \
  ".venv/bin/python" \
  ".venv/Scripts/python.exe" \
  "/mnt/c/Python313/python.exe"
do
  if command -v "${candidate}" >/dev/null 2>&1 || [[ -x "${candidate}" ]]; then
    if "${candidate}" -c "import fastapi, pydantic, prometheus_client" >/dev/null 2>&1; then
      PYTHON_BIN="${candidate}"
      break
    fi
  fi
done

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "ERROR: could not find a Python interpreter with required modules (fastapi, pydantic, prometheus_client)." >&2
  exit 1
fi

if [[ ! -f "services/api/main.py" || ! -f "services/scheduler/main.py" ]]; then
  echo "ERROR: run this script from the repository root context." >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"
rm -f "${OUT_DIR}/03-tenant-isolation.txt" \
      "${OUT_DIR}/04-fairness-quota.txt" \
      "${OUT_DIR}/05-rate-limit.txt" \
      "${OUT_DIR}/06-metrics-scrape.txt"

echo "Phase 4 demo harness (verification-only)"
echo "Output directory: ${OUT_DIR}"
echo "Using env: TENANT_MAX_RUNNING=${TENANT_MAX_RUNNING}, TENANT_SUBMIT_RPS=${TENANT_SUBMIT_RPS}, TENANT_SUBMIT_BURST=${TENANT_SUBMIT_BURST}, SCHEDULER_METRICS_PORT=${SCHEDULER_METRICS_PORT}"
echo

"${PYTHON_BIN}" - "${OUT_DIR}" "${TENANT_SUBMIT_RPS}" "${TENANT_SUBMIT_BURST}" <<'PY'
import sys
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from pkg.job_system.models import Job
from services.api.main import app, get_repository, get_submit_limiter, TenantRateLimiter

out_dir = sys.argv[1]
submit_rps = float(sys.argv[2])
submit_burst = int(sys.argv[3])

class Repo:
    def __init__(self) -> None:
        self.jobs: dict[UUID, Job] = {}
        self.by_idempotency: dict[str, UUID] = {}

    def create_job(
        self,
        *,
        tenant_id: str,
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
        submitted_by: str | None = None,
        request_id: str | None = None,
        created_from_ip: str | None = None,
    ) -> Job:
        now = datetime.now(timezone.utc)
        job = Job(
            id=uuid4(),
            tenant_id=tenant_id,
            image=image,
            command=command or [],
            args=args or [],
            queue=queue,
            env=env or {},
            resources=resources or {},
            priority=priority,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
            submitted_by=submitted_by,
            request_id=request_id,
            created_from_ip=created_from_ip,
            status="QUEUED",
            attempts=0,
            created_at=now,
            updated_at=now,
            queued_at=now,
            next_retry_at=now,
        )
        self.jobs[job.id] = job
        if idempotency_key:
            self.by_idempotency[idempotency_key] = job.id
        return job

    def get_job_by_idempotency_key(self, key: str) -> Job | None:
        jid = self.by_idempotency.get(key)
        return self.jobs.get(jid) if jid else None

    def get_job_for_tenant(self, tenant_id: str, job_id: UUID) -> Job | None:
        job = self.jobs.get(job_id)
        if not job or job.tenant_id != tenant_id:
            return None
        return job

    def get_status_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for job in self.jobs.values():
            out[job.status] = out.get(job.status, 0) + 1
        return out

    def get_status_counts_by_tenant_status(self) -> list[dict[str, Any]]:
        counts: dict[tuple[str, str], int] = {}
        for job in self.jobs.values():
            key = (job.tenant_id, job.status)
            counts[key] = counts.get(key, 0) + 1
        return [
            {"tenant_id": tenant, "status": status, "count": count}
            for (tenant, status), count in counts.items()
        ]

    def get_reliability_totals(self) -> dict[str, int]:
        return {"success_total": 0, "fail_total": 0, "retries_total": 0}

repo = Repo()
limiter = TenantRateLimiter(rps=submit_rps, burst=submit_burst)
app.dependency_overrides[get_repository] = lambda: repo
app.dependency_overrides[get_submit_limiter] = lambda: limiter
client = TestClient(app)

# tenant isolation proof
created = client.post("/jobs", json={"image": "busybox:1.36"}, headers={"X-Tenant-Id": "tenant-a"})
job_id = created.json()["job_id"]
cross = client.get(f"/jobs/{job_id}", headers={"X-Tenant-Id": "tenant-b"})
owner = client.get(f"/jobs/{job_id}", headers={"X-Tenant-Id": "tenant-a"})
with open(f"{out_dir}/03-tenant-isolation.txt", "w", encoding="utf-8") as f:
    f.write(f"created_status= {created.status_code}\n")
    f.write(f"job_id= {job_id}\n")
    f.write(f"cross_tenant_get_status= {cross.status_code}\n")
    f.write(f"cross_tenant_get_body= {cross.json()}\n")
    f.write(f"owner_get_status= {owner.status_code}\n")
    f.write(f"owner_tenant= {owner.json().get('tenant_id')}\n")

# rate limit proof
statuses = []
for _ in range(3):
    r = client.post("/jobs", json={"image": "busybox:1.36"}, headers={"X-Tenant-Id": "tenant-z"})
    statuses.append((r.status_code, r.headers.get("Retry-After"), r.json()))
metrics_text = client.get("/metrics").text
with open(f"{out_dir}/05-rate-limit.txt", "w", encoding="utf-8") as f:
    f.write(f"burst_statuses= {statuses}\n")
    f.write(f"jobs_persisted= {len(repo.jobs)}\n\n")
    f.write("metrics_excerpt:\n")
    for line in metrics_text.splitlines():
        if (
            "job_system_api_submit_rate_limited_total" in line
            or "job_system_api_submit_rate_limited_by_tenant_bucket_total" in line
        ) and not line.startswith("#"):
            f.write(f"{line}\n")

app.dependency_overrides.clear()
PY

"${PYTHON_BIN}" - "${OUT_DIR}" "${TENANT_MAX_RUNNING}" "${SCHEDULER_METRICS_PORT}" <<'PY'
import io
import logging
import sys
import time
import urllib.request
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from prometheus_client import start_http_server

from pkg.job_system.models import Job
from services.api.main import app, get_repository, get_submit_limiter, TenantRateLimiter
from services.scheduler.main import Scheduler

out_dir = sys.argv[1]
tenant_max_running = int(sys.argv[2])
_scheduler_metrics_port = int(sys.argv[3])

class Repo:
    def __init__(self, jobs):
        self.jobs = {j.id: j for j in jobs}
        self.job_order = [j.id for j in jobs]
        self.dispatch_order = []

    def list_dispatchable_jobs(self, limit=5):
        ordered = [self.jobs[jid] for jid in self.job_order]
        return [j for j in ordered if j.status == "QUEUED"][:limit]

    def count_running_jobs_by_tenant(self, tenant_id):
        return sum(
            1 for j in self.jobs.values() if j.tenant_id == tenant_id and j.status == "RUNNING"
        )

    def mark_job_running(self, job_id):
        job = self.jobs[job_id]
        if job.status != "QUEUED":
            return None
        job.status = "RUNNING"
        job.attempts += 1
        self.dispatch_order.append(job.tenant_id)
        return job

    def create_job(self, **kwargs):
        now = datetime.now(timezone.utc)
        job = Job(
            id=uuid4(),
            tenant_id=kwargs["tenant_id"],
            image=kwargs["image"],
            command=kwargs.get("command") or [],
            args=kwargs.get("args") or [],
            queue=kwargs.get("queue", "default"),
            env=kwargs.get("env") or {},
            resources=kwargs.get("resources") or {},
            priority=kwargs.get("priority", 0),
            max_retries=kwargs.get("max_retries", 0),
            backoff_seconds=kwargs.get("backoff_seconds", 5),
            timeout_seconds=kwargs.get("timeout_seconds"),
            status="QUEUED",
            attempts=0,
            created_at=now,
            updated_at=now,
            queued_at=now,
            next_retry_at=now,
        )
        self.jobs[job.id] = job
        self.job_order.append(job.id)
        return job

    def get_job_by_idempotency_key(self, key):
        return None

    def get_status_counts(self):
        out = {}
        for j in self.jobs.values():
            out[j.status] = out.get(j.status, 0) + 1
        return out

    def get_status_counts_by_tenant_status(self):
        counts = {}
        for j in self.jobs.values():
            key = (j.tenant_id, j.status)
            counts[key] = counts.get(key, 0) + 1
        return [{"tenant_id": t, "status": s, "count": c} for (t, s), c in counts.items()]

    def get_reliability_totals(self):
        return {"success_total": 0, "fail_total": 0, "retries_total": 0}

def q(tenant):
    now = datetime.now(timezone.utc)
    return Job(
        id=uuid4(),
        tenant_id=tenant,
        image="busybox:1.36",
        command=["sh", "-c"],
        args=["echo q"],
        queue="default",
        status="QUEUED",
        attempts=0,
        priority=0,
        max_retries=0,
        backoff_seconds=5,
        timeout_seconds=None,
        created_at=now,
        updated_at=now,
        queued_at=now,
        next_retry_at=now,
    )

def r(tenant):
    now = datetime.now(timezone.utc)
    return Job(
        id=uuid4(),
        tenant_id=tenant,
        image="busybox:1.36",
        command=["sh", "-c"],
        args=["echo run"],
        queue="default",
        status="RUNNING",
        attempts=1,
        priority=0,
        max_retries=0,
        backoff_seconds=5,
        timeout_seconds=None,
        created_at=now,
        updated_at=now,
        queued_at=now,
        started_at=now,
    )

# fairness scenario
repo_fair = Repo([q("tenant-a"), q("tenant-a"), q("tenant-b"), q("tenant-b")])
s1 = Scheduler.__new__(Scheduler)
s1.repo = repo_fair
s1.dispatch_batch_size = 4
s1.dispatch_candidate_multiplier = 5
s1.tenant_max_running = 10
s1._rr_last_tenant = None
s1._ensure_k8s_job_exists = lambda job, attempt: True
s1._dispatch_queued_jobs()

# quota scenario with logs
log_stream = io.StringIO()
handler = logging.StreamHandler(log_stream)
handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
logger = logging.getLogger("job-system-scheduler")
logger.handlers = [handler]
logger.setLevel(logging.INFO)
logger.propagate = False

repo_quota = Repo([r("tenant-a"), q("tenant-a"), q("tenant-b")])
s2 = Scheduler.__new__(Scheduler)
s2.repo = repo_quota
s2.dispatch_batch_size = 2
s2.dispatch_candidate_multiplier = 5
s2.tenant_max_running = tenant_max_running
s2._rr_last_tenant = None
s2._ensure_k8s_job_exists = lambda job, attempt: True
s2._dispatch_queued_jobs()

app.dependency_overrides[get_repository] = lambda: repo_quota
shared_limiter = TenantRateLimiter(rps=1.0, burst=1)
app.dependency_overrides[get_submit_limiter] = lambda: shared_limiter
client = TestClient(app)
client.post("/jobs", json={"image": "busybox:1.36"}, headers={"X-Tenant-Id": "tenant-z"})
client.post("/jobs", json={"image": "busybox:1.36"}, headers={"X-Tenant-Id": "tenant-z"})
api_metrics = client.get("/metrics").text

with open(f"{out_dir}/04-fairness-quota.txt", "w", encoding="utf-8") as f:
    f.write(f"dispatch_order_fairness= {repo_fair.dispatch_order}\n")
    f.write("expected_rr_prefix= ['tenant-a', 'tenant-b', 'tenant-a', 'tenant-b']\n\n")
    f.write("metrics_excerpt:\n")
    for line in api_metrics.splitlines():
        if (
            "job_system_scheduler_dispatch_decisions_total" in line
            or "job_system_scheduler_quota_blocks_total" in line
            or "job_system_scheduler_quota_blocks_by_tenant_bucket_total" in line
        ) and not line.startswith("#"):
            f.write(f"{line}\n")
    f.write("\nlog_excerpt:\n")
    for line in log_stream.getvalue().splitlines():
        if "dispatch_skipped_tenant_quota" in line or "job_running tenant_id=" in line:
            f.write(f"{line}\n")

# scheduler metrics surface scrape demo (local probe)
start_http_server(19006)
time.sleep(0.1)
raw = urllib.request.urlopen("http://127.0.0.1:19006/metrics").read().decode("utf-8")
with open(f"{out_dir}/06-metrics-scrape.txt", "w", encoding="utf-8") as f:
    f.write("API_METRICS:\n")
    for line in api_metrics.splitlines():
        if (
            "job_system_jobs_queued " in line
            or "job_system_jobs_running " in line
            or "job_system_scheduler_dispatch_decisions_total{decision=\"dispatched\"}" in line
            or "job_system_scheduler_quota_blocks_total " in line
            or "job_system_api_submit_rate_limited_total " in line
        ) and not line.startswith("#"):
            f.write(f"{line}\n")
    f.write("\nSCHEDULER_METRICS_PORT_SCRAPE:\n")
    for line in raw.splitlines():
        if (
            "job_system_jobs_queued " in line
            or "job_system_jobs_running " in line
            or "job_system_scheduler_dispatch_decisions_total{decision=\"dispatched\"}" in line
            or "job_system_scheduler_quota_blocks_total " in line
            or "job_system_api_submit_rate_limited_total " in line
        ) and not line.startswith("#"):
            f.write(f"{line}\n")

app.dependency_overrides.clear()
PY

echo "Demo complete."
echo "Generated:"
echo "  ${OUT_DIR}/03-tenant-isolation.txt"
echo "  ${OUT_DIR}/04-fairness-quota.txt"
echo "  ${OUT_DIR}/05-rate-limit.txt"
echo "  ${OUT_DIR}/06-metrics-scrape.txt"
echo
echo "What to look for:"
echo "  - 404 on cross-tenant read"
echo "  - alternating dispatch order and quota block signals"
echo "  - 429 with Retry-After and rate-limit counter increments"
echo "  - API and scheduler metrics scrape excerpts with non-zero counters"
