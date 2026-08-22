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
    local dir="$1"
    local name="$2"
    local version="$3"
    local reason="$4"

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

write_package alpha-1.0-1 alpha 1.0-1 0
write_package beta-2.0-1 beta 2.0-1 1

echo "=== snapshot does not auto-trust ==="
"$ROOT/bin/maho-provenance" snapshot >/dev/null
BASELINE="$XDG_STATE_HOME/maho/security/provenance/baseline.json"
[ ! -e "$BASELINE" ] || { echo "FAIL: snapshot became trusted automatically" >&2; exit 1; }
"$ROOT/bin/maho-provenance" check | grep -q 'No trusted package baseline'
echo "PASS"

echo "=== explicit baseline ==="
SNAPSHOT="$(find "$XDG_STATE_HOME/maho/security/provenance/snapshots" -type f -name '*.json' | head -1)"
[ -n "$SNAPSHOT" ]
"$ROOT/bin/maho-provenance" baseline set "$SNAPSHOT" >/dev/null
[ -f "$BASELINE" ]
"$ROOT/bin/maho-provenance" check >/dev/null

# shellcheck source=../lib/events.sh
source "$ROOT/lib/events.sh"
maho_event_last security | python -c '
import json, sys
e = json.load(sys.stdin)
assert e["kind"] == "packages.check"
assert e["status"] == "verified"
'
echo "PASS"

echo "=== package drift is evidence ==="
rm -rf "$MAHO_PACMAN_DB_ROOT/alpha-1.0-1" "$MAHO_PACMAN_DB_ROOT/beta-2.0-1"
write_package beta-2.1-1 beta 2.1-1 1
write_package gamma-3.0-1 gamma 3.0-1 0

"$ROOT/bin/maho-provenance" check >/dev/null
maho_event_last security | python -c '
import json, sys
e = json.load(sys.stdin)
assert e["kind"] == "packages.changed"
assert e["status"] == "observed"
assert e["risk"] == "info"
d = e["details"]
assert d["added"] == ["gamma"]
assert d["removed"] == ["alpha"]
assert len(d["changed"]) == 1
assert d["changed"][0]["name"] == "beta"
assert d["changed"][0]["before"] == "2.0-1"
assert d["changed"][0]["after"] == "2.1-1"
'
echo "PASS"

echo "ALL PROVENANCE CONTRACTS PASS"
