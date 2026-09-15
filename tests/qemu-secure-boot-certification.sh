#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="${1:-$ROOT/.cert-work/qemu}"
TOOL_ROOT="${MAHO_CERT_TOOL_ROOT:-/}"

python "$ROOT/tools/build-qemu-secure-boot-fixtures.py" \
  --output "$OUTPUT" \
  --tool-root "$TOOL_ROOT"

python "$ROOT/tools/qemu-secure-boot-certify.py" \
  "$OUTPUT/plan.json" \
  --timeout 15 \
  > "$OUTPUT/result.json"

python "$ROOT/tests/test_boot_publication.py"

python - "$OUTPUT/result.json" <<'PY'
import json
import pathlib
import sys

result = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert result["passed"] is True
assert len(result["results"]) == 13
assert all(row["passed"] is True for row in result["results"])
print("ALL QEMU/OVMF SECURE BOOT CERTIFICATION SCENARIOS PASS")
PY
