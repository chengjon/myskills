#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${FT_GOVERNANCE_SCRIPT:-}" ]]; then
  exec node "$FT_GOVERNANCE_SCRIPT" scope-check "$@"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CANDIDATE="$SCRIPT_DIR/../scripts/ft-governance.cjs"

if [[ -f "$CANDIDATE" ]]; then
  exec node "$CANDIDATE" scope-check "$@"
fi

echo "ERROR set FT_GOVERNANCE_SCRIPT to function-tree-governance/scripts/ft-governance.cjs" >&2
exit 2
