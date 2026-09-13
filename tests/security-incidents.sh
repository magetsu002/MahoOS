#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_STATE_HOME="$TMP/state"
export XDG_CONFIG_HOME="$TMP/config"
export MAHO_ROOT="$ROOT"
export MAHO_PACMAN_DB_ROOT="$TMP/pacman-local"

STATE="$XDG_STATE_HOME/maho/security"
MON="$STATE/monitor-v2"
DB="$MAHO_PACMAN_DB_ROOT"
mkdir -p "$HOME" "$XDG_STATE_HOME" "$XDG_CONFIG_HOME" "$MON" "$STATE/findings" "$DB/alpha-1.0-1"

cat > "$DB/alpha-1.0-1/desc" <<'EOF_DESC'
%NAME%
alpha

%VERSION%
1.0-1

%FILES%
usr/bin/alpha
usr/lib/systemd/system/alpha.service

EOF_DESC

cat > "$MON/runtime.json" <<EOF_RUNTIME
{"version":1,"kind":"runtime-executable-observations","result":"observed","observations":[{"pid":222,"uid":$(id -u),"name":"alpha","exe":"/usr/bin/alpha (deleted)","relative_exe":"usr/bin/alpha","deleted":true,"signals":["deleted-executable"],"risk":"medium"}]}
EOF_RUNTIME

cat > "$MON/integrity.json" <<'EOF_INTEGRITY'
{"version":1,"kind":"package-file-integrity","result":"changed","modified":[{"package":"alpha","version":"1.0-1","path":"/usr/bin/alpha"}],"missing":[],"type_changed":[],"unreadable":[]}
EOF_INTEGRITY

cat > "$MON/persistence.json" <<'EOF_PERSIST'
{"result":"changed","added":[{"path":"/etc/systemd/system/alpha.service","kind":"systemd-system","type":"symlink","target":"/usr/lib/systemd/system/alpha.service"}],"removed":[],"changed":[]}
EOF_PERSIST

cat > "$STATE/findings/alpha.json" <<'EOF_FINDING'
{
  "version": 1,
  "id": "incident-test-001",
  "source": "test-feed",
  "type": "package-version",
  "severity": "critical",
  "confidence": "confirmed",
  "summary": "Alpha 1.0-1 is confirmed affected.",
  "package": {"name": "alpha", "versions": ["1.0-1"]}
}
EOF_FINDING

fail() { echo "FAIL: $*" >&2; exit 1; }

echo "=== repeated copies of one evidence class do not inflate risk ==="
python - "$ROOT" <<'PY_DUPLICATES'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "lib"))
from security_incident import build_incident, signal
item=signal("runtime-executable", "procfs", 25, {"pid":222,"exe":"/usr/bin/alpha (deleted)"})
one=build_incident("host","local",[item],"shadow","confirmed",False,False)
many=build_incident("host","local",[item for _ in range(50)],"shadow","confirmed",False,False)
assert many["score"] == one["score"], (one,many)
assert many["risk"] == one["risk"], (one,many)
assert len(many["signals"]) == 1, many
assert len(many["signals"][0].get("correlated", [])) == 8, many
PY_DUPLICATES
echo "PASS"

echo "=== independent signals become one package incident ==="
OUTPUT="$(bash "$ROOT/bin/maho-guard" reconcile)"
grep -q 'Active:' <<< "$OUTPUT"
ACTIVE="$STATE/incidents/active"
[ "$(find "$ACTIVE" -maxdepth 1 -type f -name 'inc-*.json' | wc -l)" -eq 2 ] || fail "expected package + host incidents"
PACKAGE_FILE="$(python - "$ACTIVE" <<'PY'
import json,sys
from pathlib import Path
for p in Path(sys.argv[1]).glob('inc-*.json'):
    d=json.loads(p.read_text())
    if d.get('subject') == {'type':'package','id':'alpha'}:
        print(p); break
PY
)"
[ -n "$PACKAGE_FILE" ] || fail "package incident missing"
python - "$PACKAGE_FILE" <<'PY'
import json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d['risk'] == 'critical', d
assert d['confidence'] == 'confirmed', d
assert d['score'] == 100, d
assert d['containment_eligible'] is True, d
assert d['response_reversible'] is True, d
assert d['shadow_action'] == 'contain-processes', d
assert d['enforced_action'] == 'none', d
assert d['attention'] == 'notification', d
assert set(s['kind'] for s in d['signals']) == {'confirmed-finding','integrity-drift','runtime-executable'}
assert d['runtime_pids'] == [222]
PY
[ "$(stat -c '%a' "$ACTIVE")" = 700 ]
[ "$(stat -c '%a' "$PACKAGE_FILE")" = 600 ]
echo "PASS"

echo "=== identical state is quiet and stable ==="
BEFORE="$(find "$XDG_STATE_HOME/maho/history" -type f -name events.jsonl -exec wc -l {} \; 2>/dev/null | awk '{s+=$1} END {print s+0}')"
bash "$ROOT/bin/maho-guard" reconcile >/dev/null
AFTER="$(find "$XDG_STATE_HOME/maho/history" -type f -name events.jsonl -exec wc -l {} \; 2>/dev/null | awk '{s+=$1} END {print s+0}')"
[ "$AFTER" -eq "$BEFORE" ] || fail "unchanged incidents emitted duplicate events"
echo "PASS"

echo "=== active evidence clearing resolves incidents instead of deleting history ==="
printf '%s\n' '{"version":1,"kind":"runtime-executable-observations","result":"clean","observations":[]}' > "$MON/runtime.json"
printf '%s\n' '{"version":1,"kind":"package-file-integrity","result":"clean","modified":[],"missing":[],"type_changed":[],"unreadable":[]}' > "$MON/integrity.json"
printf '%s\n' '{"result":"clean","added":[],"removed":[],"changed":[]}' > "$MON/persistence.json"
rm -f "$STATE/findings/alpha.json"
bash "$ROOT/bin/maho-guard" reconcile >/dev/null
[ "$(find "$ACTIVE" -maxdepth 1 -type f -name 'inc-*.json' | wc -l)" -eq 0 ] || fail "resolved incidents remained active"
ARCHIVE="$STATE/incidents/archive"
[ "$(find "$ARCHIVE" -maxdepth 1 -type f -name 'inc-*.json' | wc -l)" -eq 2 ] || fail "resolved incidents were not archived"
python - "$XDG_STATE_HOME/maho/history/events.jsonl" <<'PY'
import json,sys
from pathlib import Path
rows=[]
for line in Path(sys.argv[1]).read_text().splitlines():
    try: rows.append(json.loads(line))
    except Exception: pass
assert sum(1 for r in rows if r.get('kind') == 'incident.created') == 2
assert sum(1 for r in rows if r.get('kind') == 'incident.resolved') == 2
PY
echo "PASS"

echo "=== expected Maho wiring drift does not open a security incident ==="
cat > "$MON/persistence.json" <<'EOF_EXPECTED_PERSIST'
{"result":"changed","attention_result":"clean","added":[{"path":"/home/test/.config/systemd/user/maho-adaptive.service","expected":true,"attribution":{"classification":"expected-maho-wiring","owner":"maho-runtime"}}],"removed":[],"changed":[],"expected_changes":[{"change":"added","path":"/home/test/.config/systemd/user/maho-adaptive.service","expected":true}],"unexpected_added":[],"unexpected_removed":[],"unexpected_changed":[]}
EOF_EXPECTED_PERSIST
bash "$ROOT/bin/maho-guard" reconcile >/dev/null
[ "$(find "$ACTIVE" -maxdepth 1 -type f -name 'inc-*.json' | wc -l)" -eq 0 ] || fail "expected Maho wiring opened an incident"
echo "PASS"

echo "=== guard doctor exposes friction and enforcement contract ==="
DOCTOR="$(bash "$ROOT/bin/maho-guard" doctor)"
grep -q 'unit of reasoning: correlated incident' <<< "$DOCTOR"
grep -q 'automatic system mutation: none' <<< "$DOCTOR"
grep -q 'default interruption: silent' <<< "$DOCTOR"
echo "PASS"

echo "=== guard doctor is read-only on immutable runtime trees ==="
IMMUTABLE="$TMP/immutable-runtime"
mkdir -p "$IMMUTABLE"
cp -a "$ROOT/lib" "$IMMUTABLE/lib"
cp -a "$ROOT/bin" "$IMMUTABLE/bin"
find "$IMMUTABLE" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$IMMUTABLE" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
find "$IMMUTABLE" -type d -exec chmod 0555 {} +
find "$IMMUTABLE" -type f -exec chmod 0444 {} +
IMMUTABLE_DOCTOR="$(MAHO_ROOT="$IMMUTABLE" bash "$IMMUTABLE/bin/maho-guard" doctor)"
for label in   'incident correlation engine'   'static package preflight engine'   'Guardian severity policy'   'Guardian recovery authority combiner'   'Guardian incident normalizer/history'   'Guardian service incident lifecycle'   'Guardian event watcher'; do
  grep -Fq "PASS  $label" <<< "$IMMUTABLE_DOCTOR" || fail "immutable doctor failed: $label"
done
[ -z "$(find "$IMMUTABLE" -type d -name __pycache__ -print -quit)" ] || fail "doctor attempted bytecode writes in immutable runtime"
chmod -R u+w "$IMMUTABLE"
echo "PASS"

echo "ALL SECURITY INCIDENT CONTRACTS PASS"
