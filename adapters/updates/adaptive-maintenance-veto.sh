#!/usr/bin/env bash
set -euo pipefail
ROOT="${MAHO_ROOT:-$HOME/Projects/Maho-OS}"
exec python "$ROOT/lib/maho_adaptive_maintenance_state.py" "$@"
