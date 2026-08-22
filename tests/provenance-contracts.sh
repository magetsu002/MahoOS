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

mkdir -p "$HOME" "$XDG_STATE_HOME" "$XDG_CONFIG_HOME" "$MAHO_PACMAN_DB_ROOT"

write_package() {
    local dir="$1" name="$2" version="$3" reason="$4"
    mkdir -p "$MAHO_PACMAN_DB_ROOT/$dir"
    cat > "$MAHO_PACMAN_DB_ROOT/$dir/desc" <<EOF_DESC
%NAME%
$name

%VERSION%
$version

%ARCH%
x86_64

%PACKAGER%
Maho Test Builder

%INSTALLDATE%
1787418000

%REASON%
$reason

%VALIDATION%
pgp

EOF_DESC
}

fail() { echo "FAIL: $*" >&2; exit 1; }

write_package alpha-1.0-1 alpha 1.0-1 0
write_package beta-2.0-1 beta 2.0-1 1

PROV="$XDG_STATE_HOME/maho/security/provenance"
BASELINE="$PROV/baseline.json"

echo "=== snapshot is private and does not auto-trust ==="
"$ROOT/bin/maho-provenance" snapshot >/dev/null
[ ! -e "$BASELINE" ] || fail "snapshot became trusted automatically"
CHECK="$("$ROOT/bin/maho-provenance" check)"
grep -q 'No trusted package baseline' <<< "$CHECK"
SNAPSHOT="$(find "$PROV/snapshots" -type f -name '*.json' | head -1)"
[ -n "$SNAPSHOT" ] || fail "snapshot was not created"
[ "$(stat -c '%a' "$PROV")" = 700 ]
[ "$(stat -c '%a' "$PROV/snapshots")" = 700 ]
[ "$(stat -c '%a' "$SNAPSHOT")" = 600 ]
[ "$(stat -c '%a' "$PROV/latest.json")" = 600 ]
echo "PASS"

echo "=== identical package state has stable identity across captures ==="
FIRST_STATE="$(python - "$SNAPSHOT" <<'PY'
import hashlib,json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
identity={"version":d["version"],"kind":d["kind"],"source":d["source"],"packages":d["packages"]}
print(hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(",",":")).encode()).hexdigest())
PY
)"
sleep 0.02
SECOND_OUTPUT="$("$ROOT/bin/maho-provenance" snapshot)"
SECOND_STATE="$(printf '%s\n' "$SECOND_OUTPUT" | awk '/State SHA256:/ {print $3}')"
[ "$FIRST_STATE" = "$SECOND_STATE" ] || fail "capture timestamp changed package-state identity"
echo "PASS"

echo "=== arbitrary external manifest cannot become trusted ==="
cp "$SNAPSHOT" "$TMP/copied-manifest.json"
if "$ROOT/bin/maho-provenance" baseline set "$TMP/copied-manifest.json" >/dev/null 2>&1; then
    fail "external manifest was accepted as trusted baseline"
fi
[ ! -e "$BASELINE" ] || fail "rejected manifest changed trusted baseline"
echo "PASS"

echo "=== explicit captured baseline ==="
"$ROOT/bin/maho-provenance" baseline set "$SNAPSHOT" >/dev/null
[ -f "$BASELINE" ]
[ "$(stat -c '%a' "$BASELINE")" = 600 ]
"$ROOT/bin/maho-provenance" check >/dev/null
source "$ROOT/lib/events.sh"
maho_event_last security | python -c '
import json,sys
e=json.load(sys.stdin)
assert e["kind"] == "packages.check"
assert e["status"] == "verified"
assert e["details"]["baseline_state_sha256"] == e["details"]["current_state_sha256"]
'
echo "PASS"

echo "=== latest alias is explicit but convenient ==="
"$ROOT/bin/maho-provenance" baseline clear >/dev/null
[ ! -e "$BASELINE" ]
"$ROOT/bin/maho-provenance" baseline set latest >/dev/null
[ -f "$BASELINE" ]
"$ROOT/bin/maho-provenance" check >/dev/null
echo "PASS"

echo "=== package drift is evidence ==="
rm -rf "$MAHO_PACMAN_DB_ROOT/alpha-1.0-1" "$MAHO_PACMAN_DB_ROOT/beta-2.0-1"
write_package beta-2.1-1 beta 2.1-1 1
write_package gamma-3.0-1 gamma 3.0-1 0

"$ROOT/bin/maho-provenance" check >/dev/null
maho_event_last security | python -c '
import json,sys
e=json.load(sys.stdin)
assert e["kind"] == "packages.changed"
assert e["status"] == "observed"
assert e["risk"] == "info"
d=e["details"]
assert d["added"] == ["gamma"]
assert d["removed"] == ["alpha"]
assert len(d["changed"]) == 1
assert d["changed"][0]["name"] == "beta"
assert d["changed"][0]["before"] == "2.0-1"
assert d["changed"][0]["after"] == "2.1-1"
assert d["baseline_state_sha256"] != d["current_state_sha256"]
'
echo "PASS"

echo "=== user can clear trust without deleting evidence ==="
SNAPSHOT_COUNT="$(find "$PROV/snapshots" -type f -name '*.json' | wc -l)"
"$ROOT/bin/maho-provenance" baseline clear >/dev/null
[ ! -e "$BASELINE" ] || fail "baseline survived explicit clear"
[ "$(find "$PROV/snapshots" -type f -name '*.json' | wc -l)" = "$SNAPSHOT_COUNT" ] || fail "clearing trust deleted captured evidence"
maho_event_last security | python -c '
import json,sys
e=json.load(sys.stdin)
assert e["kind"] == "packages.baseline-cleared"
assert e["source"] == "user"
'
echo "PASS"

echo "ALL PROVENANCE CONTRACTS PASS"
