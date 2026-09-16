#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
POLICY="$ROOT/config/platform/maho-host-firewall.nft"
[ -r "$POLICY" ] || { echo "missing firewall policy" >&2; exit 1; }

require() {
  grep -Fq -- "$1" "$POLICY" || { echo "missing firewall rule: $1" >&2; exit 1; }
}

require 'ct state { established, related } accept'
require 'iifname "lo" accept'
require 'udp sport 67 udp dport 68 accept'
require 'udp sport 547 udp dport 546 accept'
require 'nd-router-advert'
require 'nd-neighbor-solicit'
require 'udp dport 9993 accept'
require 'ip daddr 224.0.0.251 udp dport 5353 accept'
require 'ip6 daddr ff02::fb udp dport 5353 accept'
require 'type filter hook input priority 10; policy drop;'

if grep -Eq 'tcp[[:space:]].*dport[[:space:]]+22[[:space:]].*accept' "$POLICY"; then
  echo "firewall policy accidentally exposes SSH" >&2
  exit 1
fi
if grep -Eq 'chain[[:space:]]+(forward|output)' "$POLICY"; then
  echo "V1 host policy must not own forward/output" >&2
  exit 1
fi

run_isolated() {
  unshare -Urn /bin/bash -s -- "$POLICY" <<'NS'
set -euo pipefail
POLICY="$1"
ip link set lo up
nft -c -f "$POLICY"
nft -f "$POLICY"

RULESET="$(nft -a list table inet maho_host)"
grep -Fq 'hook input priority filter + 10; policy drop;' <<<"$RULESET"
grep -Fq 'ct state { established, related } accept' <<<"$RULESET"
grep -Fq 'iifname "lo" accept' <<<"$RULESET"
if grep -Eq 'chain[[:space:]]+(forward|output)' <<<"$RULESET"; then
  echo "isolated ruleset unexpectedly owns forward/output" >&2
  exit 1
fi

python - <<'PY'
import socket, threading
server=socket.socket()
server.bind(('127.0.0.1', 0))
server.listen(1)
port=server.getsockname()[1]
def serve():
    conn,_=server.accept()
    conn.sendall(b'ok')
    conn.close()
threading.Thread(target=serve, daemon=True).start()
client=socket.create_connection(('127.0.0.1', port), timeout=2)
assert client.recv(2)==b'ok'
client.close(); server.close()
PY

BEFORE="$(nft -j list table inet maho_host)"
BAD="$(mktemp)"
cat > "$BAD" <<'EOF'
destroy table inet maho_host
table inet maho_host {
  chain input {
    type filter hook input priority 10; policy drop;
    this is intentionally invalid
  }
}
EOF
if nft -f "$BAD" >/dev/null 2>&1; then
  echo "invalid replacement unexpectedly loaded" >&2
  exit 1
fi
rm -f "$BAD"
AFTER="$(nft -j list table inet maho_host)"
[ "$BEFORE" = "$AFTER" ] || {
  echo "failed nft transaction changed the prior Maho table" >&2
  exit 1
}
NS
}

if ! unshare -Urn true >/dev/null 2>&1; then
  echo "SKIP: unprivileged user/network namespaces unavailable"
  exit 0
fi
run_isolated
echo 'ALL FIREWALL POLICY NAMESPACE CONTRACTS PASS'
