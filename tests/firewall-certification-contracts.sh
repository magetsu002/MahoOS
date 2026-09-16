#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT
cat > "$TMP/nft.json" <<'EOF'
{"nftables":[{"chain":{"family":"inet","table":"filter","name":"input","hook":"input","priority":0,"policy":"drop"}}]}
EOF
for context in normal-wifi mullvad-disconnected mullvad-connected zerotier-active; do
  MAHO_ROOT="$ROOT" "$ROOT/bin/maho-firewall-certify" capture "$context" --nft-json "$TMP/nft.json" --state-root "$TMP/state" >/dev/null
done
OUT="$(MAHO_ROOT="$ROOT" "$ROOT/bin/maho-firewall-certify" status --state-root "$TMP/state")"
python - "$OUT" <<'PY'
import json,sys
r=json.loads(sys.argv[1])
assert r['complete'] is True,r
assert set(r['contexts'])=={'normal-wifi','mullvad-disconnected','mullvad-connected','zerotier-active'},r
assert all(x['state']=='captured' for x in r['contexts'].values()),r
PY
printf '{"nftables":[]}' > "$TMP/empty.json"
OUT="$(MAHO_ROOT="$ROOT" "$ROOT/bin/maho-firewall-certify" inspect normal-wifi --nft-json "$TMP/empty.json")"
python - "$OUT" <<'PY'
import json,sys
r=json.loads(sys.argv[1])
assert r['result']=='insufficient-visibility',r
assert r['coverage']['ipv4_input']=='unavailable',r
assert r['coverage']['ipv6_input']=='unavailable',r
PY
echo 'ALL FIREWALL CERTIFICATION CONTRACTS PASS'
