#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_STATE_HOME="$TMP/state"
export XDG_CONFIG_HOME="$TMP/config"
export MAHO_ROOT="$ROOT"
export MAHO_PACMAN_DB_ROOT="$TMP/pacman-local"

mkdir -p "$HOME" "$XDG_STATE_HOME" "$XDG_CONFIG_HOME" "$MAHO_PACMAN_DB_ROOT/beta-2.0-1"

cat > "$MAHO_PACMAN_DB_ROOT/beta-2.0-1/desc" <<'EOF_DESC'
%NAME%
beta

%VERSION%
2.0-1

%ARCH%
x86_64

%PACKAGER%
Maho Test Builder

EOF_DESC

AFFECTED="$TMP/affected.json"
cat > "$AFFECTED" <<'EOF_FINDING'
{
  "version": 1,
  "id": "test-advisory-001",
  "source": "test-feed",
  "type": "package-version",
  "severity": "critical",
  "confidence": "confirmed",
  "summary": "Test package release is known affected.",
  "package": {"name": "beta", "versions": ["2.0-1"]}
}
EOF_FINDING

SAFE="$TMP/safe.json"
cat > "$SAFE" <<'EOF_FINDING'
{
  "version": 1,
  "id": "test-advisory-002",
  "source": "test-feed",
  "type": "package-version",
  "severity": "high",
  "confidence": "high",
  "summary": "Another beta release is affected.",
  "package": {"name": "beta", "versions": ["9.9-9"]}
}
EOF_FINDING

INVALID="$TMP/invalid.json"
cat > "$INVALID" <<'EOF_FINDING'
{
  "version": 1,
  "id": "bad",
  "source": "test-feed",
  "type": "package-range",
  "severity": "high",
  "confidence": "high",
  "summary": "Unsupported range finding.",
  "package": {"name": "beta", "versions": ["<3"]}
}
EOF_FINDING

echo "=== finding validation ==="
"$ROOT/bin/maho-security" validate "$AFFECTED" | python -c '
import json,sys
f=json.load(sys.stdin)
assert f["version"] == 1
assert f["type"] == "package-version"
assert f["package"]["name"] == "beta"
assert f["package"]["versions"] == ["2.0-1"]
'
if "$ROOT/bin/maho-security" validate "$INVALID" >/dev/null 2>&1; then
    echo "FAIL: unsupported finding type was accepted" >&2; exit 1
fi
echo "PASS"

echo "=== installed affected version ==="
"$ROOT/bin/maho-security" evaluate "$AFFECTED" | grep -q 'affected'
# shellcheck source=../lib/events.sh
source "$ROOT/lib/events.sh"
maho_event_last security | python -c '
import json,sys
e=json.load(sys.stdin)
assert e["kind"] == "supply-chain.package-match"
assert e["status"] == "observed"
assert e["risk"] == "critical"
assert e["details"]["package"] == "beta"
assert e["details"]["installed_version"] == "2.0-1"
assert e["details"]["confidence"] == "confirmed"
'
echo "PASS"

echo "=== installed version not affected ==="
"$ROOT/bin/maho-security" evaluate "$SAFE" | grep -q 'not-affected'
maho_event_last security | python -c '
import json,sys
e=json.load(sys.stdin)
assert e["kind"] == "supply-chain.package-check"
assert e["status"] == "verified"
assert e["risk"] == "info"
assert e["details"]["installed_version"] == "2.0-1"
'
echo "PASS"

echo "=== affected evidence becomes proposal in one wheel cycle ==="
OUTPUT="$("$ROOT/bin/maho-security" process "$AFFECTED")"
RESULT="$(printf '%s\n' "$OUTPUT" | tail -1)"
printf '%s\n' "$RESULT" | python -c '
import json,sys
r=json.load(sys.stdin)
assert r["status"] == "proposed"
assert r["action"] == "propose"
assert r["domain"] == "security"
assert r["cycle_id"].startswith("cyc-security-")
'
CYCLE_ID="$(printf '%s\n' "$RESULT" | python -c 'import json,sys; print(json.load(sys.stdin)["cycle_id"])')"
maho_event_cycle "$CYCLE_ID" | python -c '
import json,sys
rows=[json.loads(line) for line in sys.stdin if line.strip()]
assert [r["kind"] for r in rows] == ["finding.assessed", "policy.decision"]
assert rows[0]["risk"] == "critical"
assert rows[1]["status"] == "proposed"
assert all(r["cycle_id"] == rows[0]["cycle_id"] for r in rows)
'
echo "PASS"

echo "=== safe evidence becomes do-nothing ==="
OUTPUT="$("$ROOT/bin/maho-security" process "$SAFE")"
RESULT="$(printf '%s\n' "$OUTPUT" | tail -1)"
printf '%s\n' "$RESULT" | python -c '
import json,sys
r=json.load(sys.stdin)
assert r["status"] == "skipped"
assert r["action"] == "do-nothing"
'
echo "PASS"

echo "=== ingest persists normalized evidence privately ==="
OUTPUT="$("$ROOT/bin/maho-security" ingest "$AFFECTED")"
printf '%s\n' "$OUTPUT" | grep -q 'Stored normalized finding:'
FINDINGS="$XDG_STATE_HOME/maho/security/findings"
[ "$(find "$FINDINGS" -maxdepth 1 -type f -name '*.json' | wc -l)" -eq 1 ]
[ "$(stat -c '%a' "$FINDINGS")" = 700 ]
FILE="$(find "$FINDINGS" -maxdepth 1 -type f -name '*.json' | head -1)"
[ "$(stat -c '%a' "$FILE")" = 600 ]
python - "$FILE" <<'PY'
import json,sys
from pathlib import Path
f=json.loads(Path(sys.argv[1]).read_text())
assert f["id"] == "test-advisory-001"
assert f["package"]["versions"] == ["2.0-1"]
PY
echo "PASS"

echo "=== safe response posture ==="
"$ROOT/bin/maho-security" doctor | grep -q 'response mode: observe'
"$ROOT/bin/maho-security" doctor | grep -q 'automatic containment: not implemented'
"$ROOT/bin/maho-security" doctor | grep -q 'adaptation executor'
echo "PASS"

echo "ALL SECURITY FINDING CONTRACTS PASS"
