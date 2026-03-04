#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 <phase> <milestone>"
  echo "Example: $0 phase4 m4.1"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 2 ]]; then
  usage
  exit 1
fi

phase="$1"
milestone="$2"
base="docs/evidence/${phase}/${milestone}"
errors=0

require_file() {
  local file="$1"
  if [[ ! -f "${file}" ]]; then
    echo "ERROR: missing required file: ${file}" >&2
    errors=$((errors + 1))
  fi
}

require_dir() {
  local dir="$1"
  if [[ ! -d "${dir}" ]]; then
    echo "ERROR: missing required directory: ${dir}" >&2
    errors=$((errors + 1))
  fi
}

require_file "${base}/runbook.md"
require_file "${base}/commands.txt"
require_dir "${base}/outputs"

if [[ -d "${base}/outputs" ]]; then
  if ! compgen -G "${base}/outputs/01-*.txt" > /dev/null; then
    echo "ERROR: expected at least one outputs/01-*.txt file under ${base}/outputs" >&2
    errors=$((errors + 1))
  fi
fi

if [[ "${errors}" -gt 0 ]]; then
  echo "Evidence check FAILED for ${phase}/${milestone} with ${errors} error(s)." >&2
  exit 1
fi

echo "Evidence check OK for ${phase}/${milestone}."
