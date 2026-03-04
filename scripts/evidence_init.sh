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

mkdir -p "${base}/outputs"

if [[ ! -f "${base}/runbook.md" ]]; then
  cat > "${base}/runbook.md" <<EOF
# ${phase^^} ${milestone^^} Runbook

## Goal
TBD

## Steps
1. TBD
2. TBD
3. TBD
EOF
fi

if [[ ! -f "${base}/commands.txt" ]]; then
  cat > "${base}/commands.txt" <<EOF
# Commands for ${phase}/${milestone}
# Fill with reproducible command sequence.
EOF
fi

touch "${base}/outputs/.keep"
echo "Initialized evidence skeleton at ${base}"
