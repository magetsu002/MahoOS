#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT

cat > "$TMP/protected.json" <<'EOF'
{"nftables":[
  {"table":{"family":"inet","name":"maho_host"}},
  {"chain":{"family":"inet","table":"maho_host","name":"input","hook":"input","prio":10,"policy":"drop"}}
]}
EOF
cat > "$TMP/empty.json" <<'EOF'
{"nftables":[]}
EOF
cat > "$TMP/ipv4-only.json" <<'EOF'
{"nftables":[{"chain":{"family":"ip","table":"filter","name":"input","hook":"input","priority":0,"policy":"drop"}}]}
EOF
cat > "$TMP/unsupported.json" <<'EOF'
{"nftables":[
  {"chain":{"family":"inet","table":"filter","name":"input","hook":"input","priority":0,"policy":"accept"}},
  {"rule":{"family":"inet","table":"filter","chain":"input","expr":[{"drop":null}]}}
]}
EOF
cat > "$TMP/conflict.json" <<'EOF'
{"nftables":[
  {"chain":{"family":"inet","table":"maho_host","name":"input","hook":"input","priority":10,"policy":"drop"}},
  {"chain":{"family":"inet","table":"mullvad","name":"input","hook":"input","priority":0,"policy":"drop"}}
]}
EOF

inspect_result() {
  local fixture="$1" expected="$2"
  local out
  out="$(MAHO_ROOT="$ROOT" "$ROOT/bin/maho-firewall-certify" inspect normal-wifi --nft-json "$fixture")"
  python - "$out" "$expected" <<'PY'
import json,sys
r=json.loads(sys.argv[1]); expected=sys.argv[2]
assert r['schema_version']==2,r
assert r['result']==expected,r
assert r['result'] in {'protected','unprotected','partial','insufficient-visibility','provider-conflict','unsupported','stale'},r
assert r['observed_at'].endswith('Z'),r
assert 'privilege_level' in r,r
assert r['context']=='normal-wifi',r
assert 'tables_inspected' in r and 'input_base_chains' in r,r
assert 'authority' in r and 'owner' in r['authority'],r
assert set(r['coverage']) >= {'ipv4_input','ipv6_input'},r
PY
}
inspect_result "$TMP/protected.json" protected
inspect_result "$TMP/empty.json" unprotected
inspect_result "$TMP/ipv4-only.json" partial
inspect_result "$TMP/unsupported.json" unsupported
inspect_result "$TMP/conflict.json" provider-conflict

OUT="$(MAHO_ROOT="$ROOT" "$ROOT/bin/maho-firewall-certify" inspect normal-wifi --nft-json "$TMP/does-not-exist.json")"
python - "$OUT" <<'PY'
import json,sys
r=json.loads(sys.argv[1])
assert r['result']=='insufficient-visibility',r
assert r['decision_usable'] is False,r
assert r['coverage']['ipv4_input']=='unavailable',r
assert r['coverage']['ipv6_input']=='unavailable',r
PY

for context in normal-wifi mullvad-disconnected mullvad-connected zerotier-active; do
  MAHO_ROOT="$ROOT" "$ROOT/bin/maho-firewall-certify" capture "$context" \
    --nft-json "$TMP/protected.json" --state-root "$TMP/state" >/dev/null
done
OUT="$(MAHO_ROOT="$ROOT" "$ROOT/bin/maho-firewall-certify" status --state-root "$TMP/state")"
python - "$OUT" <<'PY'
import json,sys
r=json.loads(sys.argv[1])
assert r['complete'] is True,r
assert set(r['contexts'])=={'normal-wifi','mullvad-disconnected','mullvad-connected','zerotier-active'},r
assert all(x['state']=='protected' and x['decision_usable'] is True for x in r['contexts'].values()),r
PY
python - "$TMP/state/normal-wifi" <<'PY'
import json, pathlib, sys
path=sorted(pathlib.Path(sys.argv[1]).glob('*.json'))[-1]
r=json.loads(path.read_text())
r['observed_at']='2000-01-01T00:00:00Z'
path.write_text(json.dumps(r)+'\n')
PY
OUT="$(MAHO_ROOT="$ROOT" "$ROOT/bin/maho-firewall-certify" status \
  --state-root "$TMP/state" --max-age-seconds 60)"
python - "$OUT" <<'PY'
import json,sys
r=json.loads(sys.argv[1])
assert r['complete'] is False,r
assert r['contexts']['normal-wifi']['state']=='stale',r
assert r['contexts']['normal-wifi']['decision_usable'] is False,r
PY

echo 'ALL FIREWALL CERTIFICATION CONTRACTS PASS'
