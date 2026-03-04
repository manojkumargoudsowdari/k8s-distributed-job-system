#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

OUT_DIR="${DEMO_OUTPUT_DIR:-docs/evidence/demos/demo.1-doc-processing/outputs}"
NS="${K8S_NAMESPACE:-default}"
CLUSTER_NAME="${KIND_CLUSTER_NAME:-ai-infra-lab}"
API_URL="${DEMO_API_URL:-http://127.0.0.1:18080}"
SCHED_METRICS_URL="${DEMO_SCHED_METRICS_URL:-http://127.0.0.1:19000/metrics}"
IMAGE_TAG="${DEMO_IMAGE_TAG:-job-system-doc-processor:0.1.0}"
TENANT_MAX_RUNNING="${TENANT_MAX_RUNNING:-1}"
TENANT_SUBMIT_RPS="${TENANT_SUBMIT_RPS:-2}"
TENANT_SUBMIT_BURST="${TENANT_SUBMIT_BURST:-5}"

mkdir -p "${OUT_DIR}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: missing required command: $1" >&2
    exit 1
  fi
}

for cmd in bash curl kubectl docker; do
  require_cmd "$cmd"
done

PYTHON_BIN=""
for c in python3 python .venv/bin/python .venv/Scripts/python.exe; do
  if command -v "$c" >/dev/null 2>&1 || [[ -x "$c" ]]; then
    PYTHON_BIN="$c"
    break
  fi
done
if [[ -z "${PYTHON_BIN}" ]]; then
  echo "ERROR: python interpreter not found" >&2
  exit 1
fi

API_PF_PID=""
SCHED_PF_PID=""
cleanup() {
  if [[ -n "${API_PF_PID}" ]]; then kill "${API_PF_PID}" >/dev/null 2>&1 || true; fi
  if [[ -n "${SCHED_PF_PID}" ]]; then kill "${SCHED_PF_PID}" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

ensure_api_reachable() {
  if curl -fsS "${API_URL}/healthz" >/dev/null 2>&1; then
    return
  fi
  echo "Starting API port-forward on 18080:80" | tee -a "${OUT_DIR}/02-image-build-and-load.txt"
  kubectl -n "${NS}" port-forward svc/job-system-api 18080:80 >/tmp/demo1-api-pf.log 2>&1 &
  API_PF_PID=$!
  for _ in $(seq 1 25); do
    if curl -fsS "${API_URL}/healthz" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  echo "ERROR: API port-forward did not become ready" >&2
  exit 1
}

ensure_scheduler_metrics_reachable() {
  if curl -fsS "${SCHED_METRICS_URL}" >/dev/null 2>&1; then
    return
  fi
  local pod
  pod="$(kubectl -n "${NS}" get pods -l app=job-system-scheduler -o jsonpath='{.items[0].metadata.name}')"
  echo "Starting scheduler metrics port-forward on 19000:9000 from pod ${pod}" | tee -a "${OUT_DIR}/02-image-build-and-load.txt"
  kubectl -n "${NS}" port-forward "pod/${pod}" 19000:9000 >/tmp/demo1-scheduler-pf.log 2>&1 &
  SCHED_PF_PID=$!
  for _ in $(seq 1 25); do
    if curl -fsS "${SCHED_METRICS_URL}" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  echo "ERROR: scheduler metrics port-forward did not become ready" >&2
  exit 1
}

submit_job() {
  local tenant="$1"
  local doc_id="$2"
  local text="$3"
  local response body code
  response="$(curl -sS -X POST "${API_URL}/jobs" \
    -H "Content-Type: application/json" \
    -H "X-Tenant-Id: ${tenant}" \
    -H "Idempotency-Key: demo1-${tenant}-${doc_id}" \
    -d "{\"image\":\"${IMAGE_TAG}\",\"command\":[\"sh\",\"-c\"],\"args\":[\"python /app/worker.py; sleep 4\"],\"env\":{\"DOC_ID\":\"${doc_id}\",\"TENANT_ID\":\"${tenant}\",\"DOC_TEXT\":\"${text}\"},\"queue\":\"default\"}" \
    -w "\\nHTTP_STATUS:%{http_code}\\n")"

  body="$(printf '%s\n' "${response}" | sed '/^HTTP_STATUS:/d')"
  code="$(printf '%s\n' "${response}" | awk -F: '/^HTTP_STATUS:/{print $2}')"

  printf '%s\n' "tenant=${tenant} doc_id=${doc_id} http_status=${code} body=${body}" >> "${OUT_DIR}/03-job-submissions.txt"

  if [[ "${code}" != "201" && "${code}" != "200" ]]; then
    echo "ERROR: job submission failed for ${tenant}/${doc_id} with status ${code}" >&2
    exit 1
  fi

  printf '%s' "${body}" | "${PYTHON_BIN}" -c "import json,sys; print(json.load(sys.stdin)['job_id'])"
}

echo "Demo.1 document processing workload" > "${OUT_DIR}/02-image-build-and-load.txt"
echo "cluster=${CLUSTER_NAME} namespace=${NS}" >> "${OUT_DIR}/02-image-build-and-load.txt"
echo "env TENANT_MAX_RUNNING=${TENANT_MAX_RUNNING} TENANT_SUBMIT_RPS=${TENANT_SUBMIT_RPS} TENANT_SUBMIT_BURST=${TENANT_SUBMIT_BURST}" >> "${OUT_DIR}/02-image-build-and-load.txt"

{
  echo "$ docker build -t ${IMAGE_TAG} apps/demo/document_processor"
  docker build -t "${IMAGE_TAG}" apps/demo/document_processor
} >> "${OUT_DIR}/02-image-build-and-load.txt" 2>&1

if command -v kind >/dev/null 2>&1 && kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
  {
    echo "$ kind load docker-image ${IMAGE_TAG} --name ${CLUSTER_NAME}"
    kind load docker-image "${IMAGE_TAG}" --name "${CLUSTER_NAME}"
  } >> "${OUT_DIR}/02-image-build-and-load.txt" 2>&1
else
  echo "kind cluster ${CLUSTER_NAME} not found; skipping kind image load" >> "${OUT_DIR}/02-image-build-and-load.txt"
fi

{
  echo "$ kubectl -n ${NS} set env deploy/job-system-scheduler TENANT_MAX_RUNNING=${TENANT_MAX_RUNNING}"
  kubectl -n "${NS}" set env deploy/job-system-scheduler "TENANT_MAX_RUNNING=${TENANT_MAX_RUNNING}"
  echo "$ kubectl -n ${NS} set env deploy/job-system-api TENANT_SUBMIT_RPS=${TENANT_SUBMIT_RPS} TENANT_SUBMIT_BURST=${TENANT_SUBMIT_BURST}"
  kubectl -n "${NS}" set env deploy/job-system-api "TENANT_SUBMIT_RPS=${TENANT_SUBMIT_RPS}" "TENANT_SUBMIT_BURST=${TENANT_SUBMIT_BURST}"
  echo "$ kubectl -n ${NS} rollout status deploy/job-system-scheduler --timeout=180s"
  kubectl -n "${NS}" rollout status deploy/job-system-scheduler --timeout=180s
  echo "$ kubectl -n ${NS} rollout status deploy/job-system-api --timeout=180s"
  kubectl -n "${NS}" rollout status deploy/job-system-api --timeout=180s
} >> "${OUT_DIR}/02-image-build-and-load.txt" 2>&1

ensure_api_reachable
ensure_scheduler_metrics_reachable

: > "${OUT_DIR}/03-job-submissions.txt"

declare -a JOB_IDS=()
# tenant-a (6 docs)
JOB_IDS+=("$(submit_job tenant-a doc-a1 'Tenant A document one focuses on deterministic summaries for demo validation.')")
JOB_IDS+=("$(submit_job tenant-a doc-a2 'Tenant A document two validates scheduler quota behavior during concurrent dispatch.')")
JOB_IDS+=("$(submit_job tenant-a doc-a3 'Tenant A document three tracks reproducible outputs and stable evidence file naming.')")
JOB_IDS+=("$(submit_job tenant-a doc-a4 'Tenant A document four confirms multi-tenant processing without platform logic changes.')")
JOB_IDS+=("$(submit_job tenant-a doc-a5 'Tenant A document five checks workload logs and JSON parsing in aggregation.')")
JOB_IDS+=("$(submit_job tenant-a doc-a6 'Tenant A document six closes the batch with predictable summary and word counts.')")
# tenant-b (3 docs)
JOB_IDS+=("$(submit_job tenant-b doc-b1 'Tenant B document one ensures fair scheduling under constrained tenant concurrency.')")
JOB_IDS+=("$(submit_job tenant-b doc-b2 'Tenant B document two verifies that smaller tenants still make progress.')")
JOB_IDS+=("$(submit_job tenant-b doc-b3 'Tenant B document three validates final aggregation ordering by document id.')")

TMP_RESULTS="${OUT_DIR}/.tmp-results.jsonl"
: > "${TMP_RESULTS}"

for job_id in "${JOB_IDS[@]}"; do
  state=""
  for _ in $(seq 1 60); do
    job_json="$(curl -sS -H "X-Tenant-Id: tenant-a" "${API_URL}/jobs/${job_id}" || true)"
    if [[ -z "${job_json}" || "${job_json}" == *"not found"* ]]; then
      job_json="$(curl -sS -H "X-Tenant-Id: tenant-b" "${API_URL}/jobs/${job_id}" || true)"
    fi
    state="$(printf '%s' "${job_json}" | "${PYTHON_BIN}" -c "import json,sys; 
try:
 d=json.load(sys.stdin); print(d.get('status',''))
except Exception:
 print('')")"
    [[ "${state}" == "SUCCEEDED" || "${state}" == "FAILED" || "${state}" == "CANCELED" ]] && break
    sleep 2
  done

  kjob="$(kubectl -n "${NS}" get jobs -l "job-system/job-id=${job_id}" -o jsonpath='{.items[0].metadata.name}')"
  pod="$(kubectl -n "${NS}" get pods -l "job-name=${kjob}" -o jsonpath='{.items[0].metadata.name}')"
  log_text="$(kubectl -n "${NS}" logs "${pod}" || true)"
  printf '%s\n' "${log_text}" | "${PYTHON_BIN}" -c "import json,sys
for line in sys.stdin:
 s=line.strip()
 if not s:
  continue
 try:
  obj=json.loads(s)
  print(json.dumps(obj, sort_keys=True))
  break
 except Exception:
  pass" >> "${TMP_RESULTS}"
done

"${PYTHON_BIN}" - "${TMP_RESULTS}" "${OUT_DIR}/04-results-aggregated.jsonl" <<'PY'
import json
import sys
from pathlib import Path

src = Path(sys.argv[1])
out = Path(sys.argv[2])
rows = []
for line in src.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
        continue
    rows.append(json.loads(line))
rows.sort(key=lambda r: r.get("doc_id", ""))
out.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8")
PY

{
  echo "scheduler_log_excerpt:"
  kubectl -n "${NS}" logs deploy/job-system-scheduler --tail=300 | grep -E "job_running|dispatch_skipped_tenant_quota|dispatch_" || true
  echo
  echo "api_metrics_excerpt:"
  curl -fsS "${API_URL}/metrics" | grep -E "job_system_scheduler_dispatch_decisions_total|job_system_scheduler_quota_blocks_total|job_system_jobs_(queued|running)" || true
  echo
  echo "scheduler_metrics_excerpt:"
  curl -fsS "${SCHED_METRICS_URL}" | grep -E "job_system_scheduler_dispatch_decisions_total|job_system_scheduler_quota_blocks_total|job_system_jobs_(queued|running)" || true
} > "${OUT_DIR}/05-fairness-and-quota-signals.txt"

{
  echo "rate_limit_probe (tenant-rate):"
  for i in 1 2 3 4 5 6; do
    curl -sS -D - -o /tmp/demo1-rate-${i}.json \
      -X POST "${API_URL}/jobs" \
      -H "Content-Type: application/json" \
      -H "X-Tenant-Id: tenant-rate" \
      -d '{"image":"busybox:1.36","command":["sh","-c"],"args":["echo rate"]}' \
      | sed -n '1,8p'
  done
  echo
  echo "api_metrics_rate_limit_excerpt:"
  curl -fsS "${API_URL}/metrics" | grep -E "job_system_api_submit_rate_limited_total|job_system_api_submit_rate_limited_by_tenant_bucket_total" || true
} > "${OUT_DIR}/06-rate-limit-optional.txt"

bash scripts/evidence_check.sh demos demo.1-doc-processing > "${OUT_DIR}/08-evidence-check.txt" 2>&1

rm -f "${TMP_RESULTS}"

echo "Demo complete."
echo "Generated outputs under ${OUT_DIR}:"
echo "  02-image-build-and-load.txt"
echo "  03-job-submissions.txt"
echo "  04-results-aggregated.jsonl"
echo "  05-fairness-and-quota-signals.txt"
echo "  06-rate-limit-optional.txt"
echo "  08-evidence-check.txt"
echo
echo "What to look for:"
echo "  - tenant-a (6 docs) and tenant-b (3 docs) submissions"
echo "  - sorted aggregated processor outputs by doc_id"
echo "  - scheduler quota/fairness signals"
echo "  - optional rate-limit probe results"
