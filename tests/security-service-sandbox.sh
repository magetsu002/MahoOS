#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT="$ROOT/systemd/user/maho-security.service"
VERIFY_HOME="$(mktemp -d)"
trap 'rm -rf "$VERIFY_HOME"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
require() { grep -Fxq "$1" "$UNIT" || fail "missing service hardening: $1"; }

echo "=== security observer service has bounded write and privilege authority ==="
for directive in \
    'UMask=0077' \
    'NoNewPrivileges=yes' \
    'PrivateTmp=yes' \
    'PrivateDevices=yes' \
    'ProtectSystem=strict' \
    'ProtectHome=read-only' \
    'ProtectKernelTunables=yes' \
    'ProtectKernelModules=yes' \
    'ProtectKernelLogs=yes' \
    'ProtectControlGroups=yes' \
    'ProtectClock=yes' \
    'LockPersonality=yes' \
    'RestrictRealtime=yes' \
    'RestrictSUIDSGID=yes' \
    'RestrictNamespaces=yes' \
    'MemoryDenyWriteExecute=yes' \
    'SystemCallArchitectures=native' \
    'CapabilityBoundingSet=' \
    'RestrictAddressFamilies=AF_UNIX' \
    'StateDirectory=maho' \
    'ReadWritePaths=%S/maho' \
    'ReadOnlyPaths=/proc /etc /usr /var/lib/pacman %h/.config %h/.local/share/maho/runtime'
do
    require "$directive"
done

# ProtectProc/ProcSubset would make the observer's cross-process executable and
# socket attribution silently incomplete.  ProtectHome=yes/tmpfs would hide the
# persistence and immutable-runtime evidence it is required to inspect.
if grep -Eq '^(ProtectProc|ProcSubset)=' "$UNIT"; then fail 'service restricts required /proc observation'; fi
if grep -Eq '^ProtectHome=(yes|tmpfs)$' "$UNIT"; then fail 'service hides required home/runtime observation'; fi
mkdir -p "$VERIFY_HOME/.local/bin"
install -m 0755 "$ROOT/bin/maho-security-monitor" "$VERIFY_HOME/.local/bin/maho-security-monitor"
HOME="$VERIFY_HOME" systemd-analyze --user verify "$UNIT" >/dev/null
echo "PASS"

echo "ALL SECURITY SERVICE SANDBOX CONTRACTS PASS"
