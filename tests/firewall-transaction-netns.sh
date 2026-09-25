#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
FW="$ROOT/bin/maho-firewall"
POLICY="$ROOT/config/platform/maho-host-firewall.nft"
[ -x "$FW" ] && [ -r "$POLICY" ] || { echo "missing firewall transaction source" >&2; exit 1; }

if ! unshare -Urn true >/dev/null 2>&1; then
  echo "SKIP: unprivileged user/network namespaces unavailable"
  exit 0
fi

unshare -Urn /bin/bash -s -- "$ROOT" "$FW" "$POLICY" <<'NS'
set -euo pipefail
ROOT="$1" FW="$2" POLICY="$3"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
export MAHO_ROOT="$ROOT"
json_true() { python -c 'import json,sys; assert json.load(sys.stdin).get(sys.argv[1]) is True' "$1"; }
normalize() { sed -E 's/[[:space:]]*# handle [0-9]+//g' | sed '/^[[:space:]]*$/d'; }

nft -f - <<'EOF'
table inet unrelated_provider {
  chain input { type filter hook input priority -200; policy accept; }
}
table inet mullvad_mock {
  chain input { type filter hook input priority -100; policy accept; }
}
EOF
UNRELATED_BEFORE="$(nft list table inet unrelated_provider | normalize)"
MULLVAD_BEFORE="$(nft list table inet mullvad_mock | normalize)"
"$FW" live-status --json | python -c 'import json,sys; x=json.load(sys.stdin); assert x["result"]=="unprotected" and x["table_present"] is False'

"$FW" apply --policy "$POLICY" --json | json_true success
"$FW" live-status --json | python -c 'import json,sys; x=json.load(sys.stdin); assert x["result"]=="protected" and x["verified"] is True'
FIRST="$(nft list table inet maho_host | normalize)"
"$FW" apply --policy "$POLICY" --json | json_true success
SECOND="$(nft list table inet maho_host | normalize)"
[ "$FIRST" = "$SECOND" ] || { echo "repeated apply is not idempotent" >&2; exit 1; }
[ "$UNRELATED_BEFORE" = "$(nft list table inet unrelated_provider | normalize)" ]
[ "$MULLVAD_BEFORE" = "$(nft list table inet mullvad_mock | normalize)" ]

cat >"$TMP/unverifiable.nft" <<'EOF'
destroy table inet maho_host
table inet maho_host {
  chain input {
    type filter hook input priority 10; policy accept;
    iifname "lo" accept
  }
}
EOF
if "$FW" apply --policy "$TMP/unverifiable.nft" --json >"$TMP/unverifiable.json"; then
  echo "verification-invalid policy unexpectedly succeeded" >&2; exit 1
fi
python - "$TMP/unverifiable.json" <<'PYINNER'
import json,sys
x=json.load(open(sys.argv[1])); assert x['success'] is False and x['rollback']=='verified'
PYINNER
[ "$FIRST" = "$(nft list table inet maho_host | normalize)" ] || { echo "verification rollback did not restore Maho policy" >&2; exit 1; }

cat >"$TMP/syntax-bad.nft" <<'EOF'
destroy table inet maho_host
table inet maho_host { chain input { type filter hook input priority 10; policy drop; this is invalid } }
EOF
! "$FW" apply --policy "$TMP/syntax-bad.nft" --json >"$TMP/syntax-bad.json"
[ "$FIRST" = "$(nft list table inet maho_host | normalize)" ]

cat >"$TMP/scope-bad.nft" <<'EOF'
flush ruleset
table inet maho_host { chain input { type filter hook input priority 10; policy drop; } }
EOF
! "$FW" apply --policy "$TMP/scope-bad.nft" --json >"$TMP/scope-bad.json"
[ "$UNRELATED_BEFORE" = "$(nft list table inet unrelated_provider | normalize)" ]
[ "$MULLVAD_BEFORE" = "$(nft list table inet mullvad_mock | normalize)" ]
[ "$FIRST" = "$(nft list table inet maho_host | normalize)" ]

"$FW" remove --json | json_true success
"$FW" live-status --json | python -c 'import json,sys; x=json.load(sys.stdin); assert x["result"]=="unprotected" and x["table_present"] is False'
"$FW" remove --json | python -c 'import json,sys; x=json.load(sys.stdin); assert x["success"] is True and x["changed"] is False'
[ "$UNRELATED_BEFORE" = "$(nft list table inet unrelated_provider | normalize)" ]
[ "$MULLVAD_BEFORE" = "$(nft list table inet mullvad_mock | normalize)" ]
NS

echo 'ALL FIREWALL TRANSACTION NAMESPACE CONTRACTS PASS'
