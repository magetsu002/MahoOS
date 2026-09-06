#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/security-validation}"
mkdir -p "$OUT/logs"

SUITES=(
  provenance-contracts.sh
  security-findings.sh
  security-probes.sh
  security-containment.sh
  security-monitor.sh
  security-incidents.sh
  security-preflight.sh
  security-boundaries.sh
  setup-live-migration-contracts.sh
)

passed=0
failed=0
pass_markers=0
results="$OUT/results.tsv"
: >"$results"

for suite in "${SUITES[@]}"; do
  log="$OUT/logs/${suite%.sh}.log"
  set +e
  bash "$ROOT/tests/$suite" >"$log" 2>&1
  status=$?
  set -e
  markers="$(grep -Ec '^PASS([ :]|$)' "$log" || true)"
  pass_markers=$((pass_markers + markers))
  if [ "$status" -eq 0 ]; then
    passed=$((passed + 1))
    printf 'PASS\t%s\t%s\n' "$suite" "$markers" >>"$results"
  else
    failed=$((failed + 1))
    printf 'FAIL\t%s\t%s\n' "$suite" "$markers" >>"$results"
    cat "$log" >&2
  fi
done

source_revision="${MAHO_SOURCE_REVISION:-${GITHUB_SHA:-}}"
if [ -z "$source_revision" ]; then
  source_revision="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || printf 'unknown')"
fi

python - "$OUT/report.json" "$results" "$pass_markers" "$source_revision" <<'PY'
import json
import pathlib
import sys

report_path = pathlib.Path(sys.argv[1])
results_path = pathlib.Path(sys.argv[2])
reported_markers = int(sys.argv[3])
revision = sys.argv[4]

suites = []
for line in results_path.read_text().splitlines():
    status, name, markers = line.split("\t")
    suites.append({
        "name": name,
        "status": status.lower(),
        "reported_pass_markers": int(markers),
    })

passed = sum(item["status"] == "pass" for item in suites)
failed = len(suites) - passed
report = {
    "schema_version": 1,
    "source_revision": revision,
    "suite_count": len(suites),
    "suites_passed": passed,
    "suites_failed": failed,
    "reported_pass_markers": reported_markers,
    "claim_scope": "deterministic repository security/reliability contracts; not a claim of complete system security",
    "suites": suites,
}
report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
PY

cat "$OUT/report.json"

if [ "$failed" -ne 0 ]; then
  echo "FAIL security validation: $failed/${#SUITES[@]} suites failed" >&2
  exit 1
fi

echo "PASS security validation: $passed/${#SUITES[@]} suites passed; $pass_markers explicit PASS markers reported"
