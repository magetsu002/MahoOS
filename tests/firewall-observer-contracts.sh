#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE="$ROOT/config/systemd/system/maho-firewall-observer.service"
TIMER="$ROOT/config/systemd/system/maho-firewall-observer.timer"
PKG="$ROOT/packaging/arch/PKGBUILD.in"

grep -Fq 'ExecStart=/usr/bin/python /usr/lib/maho/lib/maho_firewall_receipt.py publish' "$SERVICE"
grep -Fq 'CapabilityBoundingSet=CAP_NET_ADMIN' "$SERVICE"
grep -Fq 'ProtectSystem=strict' "$SERVICE"
grep -Fq 'ProtectHome=yes' "$SERVICE"
grep -Fq 'ReadWritePaths=/run/maho/firewall' "$SERVICE"
! grep -Eq 'CAP_SYS_ADMIN|CAP_DAC_OVERRIDE|CAP_SYS_PTRACE' "$SERVICE"
grep -Fq 'OnUnitActiveSec=15s' "$TIMER"
grep -Fq 'maho-firewall-observer.service' "$PKG"
grep -Fq 'maho-firewall-observer.timer' "$PKG"
grep -Fq 'maho-firewall.conf' "$PKG"
grep -Eq "'nftables'" "$PKG"

OUT="$(mktemp)"; trap 'rm -f "$OUT"' EXIT
if MAHO_ROOT="$ROOT" "$ROOT/bin/maho-firewall" status --receipt /definitely/missing --json >"$OUT" 2>/dev/null; then
  echo "missing receipt unexpectedly became usable" >&2; exit 1
fi
python - "$OUT" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]))
assert r["result"]=="unknown",r
assert r["decision_usable"] is False,r
assert r["receipt_valid"] is False,r
PY
echo 'PASS missing observer receipt remains UNKNOWN'
echo 'ALL FIREWALL OBSERVER CONTRACTS PASS'
