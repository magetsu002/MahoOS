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
  "package": {
    "name": "beta",
    "versions": ["2.0-1"]
  }
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
  "package": {
    "name": "beta",
    "versions": ["9.9-9"]
  }
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
  "package": {
    "name": "beta",
    "versions": ["<3"]
  }
}
EOF_FINDING

echo "=== finding validation ==="
"$ROOT/bin/maho-security" validate "$AFFECTED" | python -c '
import json, sys
f = json.load(sys.stdin)
assert f["version"] == 1
assert f["type"] == "package-version"
assert f["package"]["name"] == "beta"
assert f["package"]["versions"] == ["2.0-1"]
'
if "$ROOT/bin/maho-security" validate "$INVALID" >/dev/null 2>&1; then
    echo "FAIL: unsupported finding type was accepted" >&2
    exit 1
fi
echo "PASS"

echo "=== installed affected version ==="
"$ROOT/bin/maho-security" evaluate "$AFFECTED" | grep -q 'affected'
# shellcheck source=../lib/events.sh
source "$ROOT/lib/events.sh"
maho_event_last security | python -c '
import json, sys
e = json.load(sys.stdin)
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
import json, sys
e = json.load(sys.stdin)
assert e["kind"] == "supply-chain.package-check"
assert e["status"] == "verified"
assert e["risk"] == "info"
assert e["details"]["installed_version"] == "2.0-1"
'
echo "PASS"

echo "=== safe response posture ==="
"$ROOT/bin/maho-security" doctor | grep -q 'response mode: observe'
"$ROOT/bin/maho-security" doctor | grep -q 'automatic containment: not implemented'
echo "PASS"

echo "ALL SECURITY FINDING CONTRACTS PASS"
