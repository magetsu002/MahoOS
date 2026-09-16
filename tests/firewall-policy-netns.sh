#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
POLICY="$ROOT/config/platform/maho-host-firewall.nft"
[ -r "$POLICY" ] || { echo "missing firewall policy" >&2; exit 1; }

require() { grep -Fq -- "$1" "$POLICY" || { echo "missing firewall rule: $1" >&2; exit 1; }; }
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
! grep -Eq 'tcp[[:space:]].*dport[[:space:]]+22[[:space:]].*accept' "$POLICY" || { echo "firewall policy accidentally exposes SSH" >&2; exit 1; }
! grep -Eq 'chain[[:space:]]+(forward|output)' "$POLICY" || { echo "V1 host policy must not own forward/output" >&2; exit 1; }

if ! unshare -Urn true >/dev/null 2>&1; then
  echo "SKIP: unprivileged user/network namespaces unavailable"
  exit 0
fi

unshare -Urn /bin/bash -s -- "$POLICY" <<'NS'
set -euo pipefail
POLICY="$1"
TMP="$(mktemp -d)"
PEER=""
cleanup() {
  [ -n "$PEER" ] && kill "$PEER" >/dev/null 2>&1 || true
  [ -n "$PEER" ] && wait "$PEER" 2>/dev/null || true
  rm -rf "$TMP"
}
trap cleanup EXIT

ip link set lo up
ip link add veth-host type veth peer name veth-peer
ip addr add 10.203.0.1/24 dev veth-host
ip -6 addr add fd42:203::1/64 dev veth-host nodad
ip link set veth-host up
unshare -n sh -c 'trap "exit 0" TERM INT; while :; do sleep 30; done' & PEER=$!
sleep .2
ip link set veth-peer netns "$PEER"
nsenter -t "$PEER" -n ip link set lo up
nsenter -t "$PEER" -n ip addr add 10.203.0.2/24 dev veth-peer
nsenter -t "$PEER" -n ip -6 addr add fd42:203::2/64 dev veth-peer nodad
nsenter -t "$PEER" -n ip link set veth-peer up
sleep .5

nft -c -f "$POLICY"
nft -f "$POLICY"
RULESET="$(nft -a list table inet maho_host)"
grep -Fq 'hook input priority filter + 10; policy drop;' <<<"$RULESET"
grep -Fq 'ct state { established, related } accept' <<<"$RULESET"
grep -Fq 'iifname "lo" accept' <<<"$RULESET"
! grep -Eq 'chain[[:space:]]+(forward|output)' <<<"$RULESET"

# Loopback remains functional.
python - <<'PY1'
import socket,threading
s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(1); port=s.getsockname()[1]
threading.Thread(target=lambda:(lambda c:(c.sendall(b'ok'),c.close()))(s.accept()[0]),daemon=True).start()
c=socket.create_connection(('127.0.0.1',port),timeout=2); assert c.recv(2)==b'ok'; c.close(); s.close()
PY1

# IPv4/IPv6 ICMP plus NDP are live, not merely parsed.
nsenter -t "$PEER" -n ping -c1 -W1 10.203.0.1 >/dev/null
nsenter -t "$PEER" -n ping -6 -c1 -W2 fd42:203::1 >/dev/null

# DHCP client replies are admitted on the exact source/destination ports.
python - "$TMP/dhcp4" <<'PY2' &
import pathlib,socket,sys
out=pathlib.Path(sys.argv[1]); s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(3); s.bind(('10.203.0.1',68)); data,_=s.recvfrom(32); out.write_bytes(data)
PY2
R4=$!
sleep .1
nsenter -t "$PEER" -n python - <<'PY3'
import socket
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.bind(('10.203.0.2',67)); s.sendto(b'dhcp4',('10.203.0.1',68))
PY3
wait "$R4"; [ "$(cat "$TMP/dhcp4")" = dhcp4 ]

python - "$TMP/dhcp6" <<'PY4' &
import pathlib,socket,sys
out=pathlib.Path(sys.argv[1]); s=socket.socket(socket.AF_INET6,socket.SOCK_DGRAM); s.settimeout(3); s.bind(('fd42:203::1',546)); data,_=s.recvfrom(32); out.write_bytes(data)
PY4
R6=$!
sleep .1
nsenter -t "$PEER" -n python - <<'PY5'
import socket
s=socket.socket(socket.AF_INET6,socket.SOCK_DGRAM); s.bind(('fd42:203::2',547)); s.sendto(b'dhcp6',('fd42:203::1',546))
PY5
wait "$R6"; [ "$(cat "$TMP/dhcp6")" = dhcp6 ]

# ZeroTier transport is explicitly reachable from IPv4 and IPv6 peers.
python - "$TMP/zt4" <<'PY6' &
import pathlib,socket,sys
out=pathlib.Path(sys.argv[1]); s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(3); s.bind(('10.203.0.1',9993)); out.write_bytes(s.recvfrom(32)[0])
PY6
Z4=$!; sleep .1
nsenter -t "$PEER" -n python -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.sendto(b'zt4',('10.203.0.1',9993))"
wait "$Z4"; [ "$(cat "$TMP/zt4")" = zt4 ]
python - "$TMP/zt6" <<'PY7' &
import pathlib,socket,sys
out=pathlib.Path(sys.argv[1]); s=socket.socket(socket.AF_INET6,socket.SOCK_DGRAM); s.settimeout(3); s.bind(('fd42:203::1',9993)); out.write_bytes(s.recvfrom(32)[0])
PY7
Z6=$!; sleep .1
nsenter -t "$PEER" -n python -c "import socket;s=socket.socket(socket.AF_INET6,socket.SOCK_DGRAM);s.sendto(b'zt6',('fd42:203::1',9993))"
wait "$Z6"; [ "$(cat "$TMP/zt6")" = zt6 ]

# Outbound TCP/DNS and their return traffic remain functional through conntrack.
nsenter -t "$PEER" -n python - <<'PY8' &
import socket
s=socket.socket(); s.bind(('10.203.0.2',18081)); s.listen(1); s.settimeout(4); c,_=s.accept(); data=c.recv(16); c.sendall(data[::-1]); c.close(); s.close()
PY8
TS=$!; sleep .1
python - <<'PY9'
import socket
c=socket.create_connection(('10.203.0.2',18081),timeout=2); c.sendall(b'outbound'); assert c.recv(16)==b'dnuobtuo'; c.close()
PY9
wait "$TS"
nsenter -t "$PEER" -n python - <<'PY10' &
import socket
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.bind(('10.203.0.2',53)); s.settimeout(4); data,addr=s.recvfrom(32); s.sendto(b'reply-'+data,addr)
PY10
DS=$!; sleep .1
python - <<'PY11'
import socket
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(2); s.sendto(b'dns',('10.203.0.2',53)); assert s.recvfrom(32)[0]==b'reply-dns'; s.close()
PY11
wait "$DS"

# New, unapproved inbound TCP/UDP is blocked for both families.
python - "$TMP/tcp4" <<'PY12' &
import pathlib,socket,sys
out=pathlib.Path(sys.argv[1]); s=socket.socket(); s.bind(('10.203.0.1',18080)); s.listen(1); s.settimeout(1.5)
try: c,_=s.accept(); out.write_text('accepted'); c.close()
except TimeoutError: out.write_text('blocked')
PY12
B4=$!; sleep .1
nsenter -t "$PEER" -n python - 2>/dev/null <<'PY13' || true
import socket
c=socket.socket(); c.settimeout(.5); c.connect(('10.203.0.1',18080))
PY13
wait "$B4"; [ "$(cat "$TMP/tcp4")" = blocked ]
python - "$TMP/tcp6" <<'PY14' &
import pathlib,socket,sys
out=pathlib.Path(sys.argv[1]); s=socket.socket(socket.AF_INET6); s.bind(('fd42:203::1',18082)); s.listen(1); s.settimeout(1.5)
try: c,_=s.accept(); out.write_text('accepted'); c.close()
except TimeoutError: out.write_text('blocked')
PY14
B6=$!; sleep .1
nsenter -t "$PEER" -n python - 2>/dev/null <<'PY15' || true
import socket
c=socket.socket(socket.AF_INET6); c.settimeout(.5); c.connect(('fd42:203::1',18082))
PY15
wait "$B6"; [ "$(cat "$TMP/tcp6")" = blocked ]
python - "$TMP/udp4" <<'PY16' &
import pathlib,socket,sys
out=pathlib.Path(sys.argv[1]); s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.bind(('10.203.0.1',5555)); s.settimeout(1.3)
try: s.recvfrom(32); out.write_text('accepted')
except TimeoutError: out.write_text('blocked')
PY16
U4=$!; sleep .1
nsenter -t "$PEER" -n python -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.sendto(b'no',('10.203.0.1',5555))"
wait "$U4"; [ "$(cat "$TMP/udp4")" = blocked ]

# Syntax failure is atomic and leaves the prior Maho table intact.
BEFORE="$(nft -j list table inet maho_host)"
BAD="$TMP/invalid.nft"
printf '%s\n' 'destroy table inet maho_host' 'table inet maho_host { chain input { type filter hook input priority 10; policy drop; this is invalid } }' >"$BAD"
! nft -f "$BAD" >/dev/null 2>&1
AFTER="$(nft -j list table inet maho_host)"
[ "$BEFORE" = "$AFTER" ]
NS

echo 'ALL FIREWALL POLICY NAMESPACE CONTRACTS PASS'
