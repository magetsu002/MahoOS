#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

FS="$TMP/fs"
PROC="$TMP/proc"
HOME_FAKE="$TMP/home"
ENGINE="$ROOT/lib/security_boundary.py"
mkdir -p \
    "$FS/etc/sudoers.d" \
    "$FS/etc/pacman.d/hooks" \
    "$FS/usr/bin" \
    "$PROC/net" \
    "$PROC/321/fd" \
    "$HOME_FAKE/.ssh"

printf 'magetsu ALL=(ALL:ALL) ALL\n' > "$FS/etc/sudoers.d/maho-test"
printf '[Trigger]\nOperation = Install\n' > "$FS/etc/pacman.d/hooks/test.hook"
printf 'ssh-ed25519 AAAATEST maho\n' > "$HOME_FAKE/.ssh/authorized_keys"
printf '#!/bin/sh\n' > "$FS/usr/bin/alpha"
chmod +x "$FS/usr/bin/alpha"

fail() { echo "FAIL: $*" >&2; exit 1; }

echo "=== privilege boundary inventory is deterministic and sensitive to changes ==="
ONE="$(python "$ENGINE" privilege --fs-root "$FS" --home "$HOME_FAKE")"
TWO="$(python "$ENGINE" privilege --fs-root "$FS" --home "$HOME_FAKE")"
H1="$(python - "$ONE" <<'PY'
import json,sys
print(json.loads(sys.argv[1])['state_sha256'])
PY
)"
H2="$(python - "$TWO" <<'PY'
import json,sys
print(json.loads(sys.argv[1])['state_sha256'])
PY
)"
[ "$H1" = "$H2" ] || fail "unchanged privilege inventory was unstable"
printf 'magetsu ALL=(ALL:ALL) NOPASSWD: ALL\n' > "$FS/etc/sudoers.d/maho-test"
THREE="$(python "$ENGINE" privilege --fs-root "$FS" --home "$HOME_FAKE")"
H3="$(python - "$THREE" <<'PY'
import json,sys
r=json.loads(sys.argv[1])
assert any(i['kind']=='sudo-policy' for i in r['items'])
assert any(i['kind']=='package-hook' for i in r['items'])
assert any(i['kind']=='ssh-authorized-keys' for i in r['items'])
print(r['state_sha256'])
PY
)"
[ "$H3" != "$H2" ] || fail "privilege boundary modification was not observed"
echo "PASS"

echo "=== non-loopback TCP listener maps to current-user process ==="
cat > "$PROC/net/tcp" <<'EOF_TCP'
  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 12345 1
EOF_TCP
cat > "$PROC/net/tcp6" <<'EOF_TCP6'
  sl  local_address                         rem_address                          st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
EOF_TCP6
cat > "$PROC/321/status" <<EOF_STATUS
Name: alpha
State: S (sleeping)
Uid: $(id -u) $(id -u) $(id -u) $(id -u)
EOF_STATUS
printf 'alpha\0--serve\0' > "$PROC/321/cmdline"
ln -s "$FS/usr/bin/alpha" "$PROC/321/exe"
ln -s 'socket:[12345]' "$PROC/321/fd/5"
OUT="$(python "$ENGINE" network --proc-root "$PROC" --fs-root "$FS" --uid "$(id -u)")"
python - "$OUT" <<'PY'
import json,sys
r=json.loads(sys.argv[1])
assert r['result']=='observed', r
assert len(r['exposed'])==1, r
x=r['exposed'][0]
assert x['pid']==321 and x['port']==8080, x
assert x['address']=='0.0.0.0' and x['exposure']=='all-interfaces', x
assert x['relative_exe']=='usr/bin/alpha', x
assert r['coverage']['host_coverage']=='partial',r
assert r['coverage']['udp']=='not-observed',r
assert r['coverage']['families']=={'ipv4':'complete','ipv6':'complete'},r
assert r['result_semantics']=='current-user-tcp-within-declared-scope-only',r
PY
echo "PASS"

echo "=== loopback-only listener is intentionally quiet ==="
cat > "$PROC/net/tcp" <<'EOF_TCP'
  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 0100007F:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 12345 1
EOF_TCP
OUT="$(python "$ENGINE" network --proc-root "$PROC" --fs-root "$FS" --uid "$(id -u)")"
python - "$OUT" <<'PY'
import json,sys
r=json.loads(sys.argv[1])
assert r['result']=='clean', r
assert len(r['listeners'])==1 and not r['exposed'], r
assert 'never equivalent to host-network-clean' in r['trust_note'],r
PY
echo "PASS"

echo "=== missing IPv6 visibility is explicit, never clean host evidence ==="
rm -f "$PROC/net/tcp6"
OUT="$(python "$ENGINE" network --proc-root "$PROC" --fs-root "$FS" --uid "$(id -u)")"
python - "$OUT" <<'PY'
import json,sys
r=json.loads(sys.argv[1])
assert r['coverage']['families']['ipv6']=='unavailable',r
assert r['coverage']['host_coverage']=='partial',r
assert r['result']=='clean',r
assert r['result_semantics'].endswith('within-declared-scope-only'),r
PY
echo "PASS"

echo "ALL SECURITY BOUNDARY CONTRACTS PASS"
