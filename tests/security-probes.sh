#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_STATE_HOME="$TMP/state"
export XDG_CONFIG_HOME="$TMP/config"
export XDG_DATA_HOME="$TMP/data"
export MAHO_ROOT="$ROOT"
export MAHO_PACMAN_DB_ROOT="$TMP/pacman-local"
export MAHO_FS_ROOT="$TMP/fs"
export MAHO_PROC_ROOT="$TMP/proc"

mkdir -p \
    "$HOME" \
    "$XDG_STATE_HOME" \
    "$XDG_DATA_HOME" \
    "$XDG_CONFIG_HOME/systemd/user/default.target.wants" \
    "$MAHO_PACMAN_DB_ROOT/beta-2.0-1" \
    "$MAHO_FS_ROOT/usr/bin" \
    "$MAHO_FS_ROOT/usr/lib/systemd/user" \
    "$MAHO_FS_ROOT/tmp" \
    "$MAHO_PROC_ROOT/111" \
    "$MAHO_PROC_ROOT/222"

printf 'good\n' > "$MAHO_FS_ROOT/usr/bin/beta"
printf '[Service]\nExecStart=/usr/bin/beta\n' > "$MAHO_FS_ROOT/usr/lib/systemd/user/beta.service"
printf 'drop\n' > "$MAHO_FS_ROOT/tmp/dropper"

BETA_SHA="$(sha256sum "$MAHO_FS_ROOT/usr/bin/beta" | awk '{print $1}')"
UNIT_SHA="$(sha256sum "$MAHO_FS_ROOT/usr/lib/systemd/user/beta.service" | awk '{print $1}')"

cat > "$MAHO_PACMAN_DB_ROOT/beta-2.0-1/desc" <<'EOF_DESC'
%NAME%
beta

%VERSION%
2.0-1

%INSTALLDATE%
1787418000

%FILES%
usr/bin/beta
usr/lib/systemd/user/beta.service

EOF_DESC

python - "$MAHO_PACMAN_DB_ROOT/beta-2.0-1/mtree" "$BETA_SHA" "$UNIT_SHA" <<'PY'
import gzip,sys
path,beta,unit=sys.argv[1:]
text=f'''#mtree
/set type=file uid=0 gid=0 mode=755
./usr/bin/beta sha256digest={beta}
./usr/lib/systemd/user/beta.service sha256digest={unit}
'''
with gzip.open(path,'wt') as f: f.write(text)
PY

ln -s "$MAHO_FS_ROOT/usr/lib/systemd/user/beta.service" \
    "$XDG_CONFIG_HOME/systemd/user/default.target.wants/beta.service"
ln -s "$MAHO_FS_ROOT/usr/bin/beta" "$MAHO_PROC_ROOT/111/exe"
cat > "$MAHO_PROC_ROOT/111/status" <<EOF_STATUS
Name:\tbeta
State:\tS (sleeping)
Uid:\t$(id -u)\t$(id -u)\t$(id -u)\t$(id -u)
EOF_STATUS
printf 'beta\0--daemon\0' > "$MAHO_PROC_ROOT/111/cmdline"

ln -s "$MAHO_FS_ROOT/tmp/dropper (deleted)" "$MAHO_PROC_ROOT/222/exe"
cat > "$MAHO_PROC_ROOT/222/status" <<EOF_STATUS
Name:\tdropper
State:\tS (sleeping)
Uid:\t$(id -u)\t$(id -u)\t$(id -u)\t$(id -u)
EOF_STATUS
printf 'dropper\0' > "$MAHO_PROC_ROOT/222/cmdline"

fail() { echo "FAIL: $*" >&2; exit 1; }

PROBE="$ROOT/lib/security_probe.py"

echo "=== critical package integrity is clean ==="
python "$PROBE" integrity \
    --scope critical \
    --db-root "$MAHO_PACMAN_DB_ROOT" \
    --fs-root "$MAHO_FS_ROOT" |
python -c '
import json,sys
r=json.load(sys.stdin)
assert r["result"] == "clean", r
assert r["checked"] == 2
assert not r["modified"]
assert not r["missing"]
'
echo "PASS"

echo "=== package impact correlates process and enabled unit ==="
python "$PROBE" impact beta \
    --version 2.0-1 \
    --db-root "$MAHO_PACMAN_DB_ROOT" \
    --proc-root "$MAHO_PROC_ROOT" \
    --fs-root "$MAHO_FS_ROOT" \
    --home "$HOME" \
    --xdg-config "$XDG_CONFIG_HOME" |
python -c '
import json,sys
r=json.load(sys.stdin)
assert r["installed"] is True
assert r["installed_version"] == "2.0-1"
assert r["version_matches"] is True
assert [p["pid"] for p in r["running_processes"]] == [111]
assert len(r["enabled_units"]) == 1
assert r["enabled_units"][0]["unit_file"] == "/usr/lib/systemd/user/beta.service"
'
echo "PASS"

echo "=== runtime probe records high-signal evidence without claiming malware ==="
python "$PROBE" runtime \
    --proc-root "$MAHO_PROC_ROOT" \
    --fs-root "$MAHO_FS_ROOT" \
    --uid "$(id -u)" |
python -c '
import json,sys
r=json.load(sys.stdin)
assert r["result"] == "observed"
row=next(x for x in r["observations"] if x["pid"] == 222)
assert "deleted-executable" in row["signals"]
assert "temporary-filesystem-executable" in row["signals"]
assert "evidence only" in r["trust_note"].lower()
'
echo "PASS"

echo "=== modified package file is evidence ==="
printf 'tampered\n' > "$MAHO_FS_ROOT/usr/bin/beta"
python "$PROBE" integrity \
    --package beta \
    --db-root "$MAHO_PACMAN_DB_ROOT" \
    --fs-root "$MAHO_FS_ROOT" |
python -c '
import json,sys
r=json.load(sys.stdin)
assert r["result"] == "changed"
assert len(r["modified"]) == 1
assert r["modified"][0]["path"] == "/usr/bin/beta"
assert "evidence" in r["trust_note"].lower()
'
printf 'good\n' > "$MAHO_FS_ROOT/usr/bin/beta"
python "$PROBE" integrity \
    --package beta \
    --db-root "$MAHO_PACMAN_DB_ROOT" \
    --fs-root "$MAHO_FS_ROOT" |
python -c 'import json,sys; r=json.load(sys.stdin); assert r["result"] == "clean" and r["checked"] == 2, r'
echo "PASS"

echo "=== unreadable package file is partial evidence ==="
chmod 000 "$MAHO_FS_ROOT/usr/lib/systemd/user/beta.service"
python "$PROBE" integrity \
    --scope critical \
    --db-root "$MAHO_PACMAN_DB_ROOT" \
    --fs-root "$MAHO_FS_ROOT" |
python -c 'import json,sys; r=json.load(sys.stdin); assert r["result"] == "partial", r; assert r["unreadable"] and r["unreadable"][0]["path"] == "/usr/lib/systemd/user/beta.service", r'
chmod 644 "$MAHO_FS_ROOT/usr/lib/systemd/user/beta.service"
echo "PASS"

echo "=== persistence snapshot never auto-trusts ==="
mkdir -p "$XDG_CONFIG_HOME/autostart"
printf '[Desktop Entry]\nType=Application\nName=Known\nExec=true\n' > "$XDG_CONFIG_HOME/autostart/known.desktop"
PERSIST_STATE="$XDG_STATE_HOME/maho/security"
python "$PROBE" persistence snapshot \
    --state-root "$PERSIST_STATE" \
    --home "$HOME" \
    --xdg-config "$XDG_CONFIG_HOME" \
    --fs-root "$MAHO_FS_ROOT" >/dev/null
[ ! -e "$PERSIST_STATE/persistence/baseline.json" ] || fail "persistence snapshot auto-trusted itself"
SNAPSHOT="$(find "$PERSIST_STATE/persistence/snapshots" -type f -name '*.json' | head -1)"
[ -n "$SNAPSHOT" ] || fail "persistence snapshot missing"
[ "$(stat -c '%a' "$PERSIST_STATE/persistence")" = 700 ]
[ "$(stat -c '%a' "$SNAPSHOT")" = 600 ]
echo "PASS"

echo "=== persistence baseline must originate from Maho snapshot store ==="
cp "$SNAPSHOT" "$TMP/external.json"
if python "$PROBE" persistence baseline-set "$TMP/external.json" \
    --state-root "$PERSIST_STATE" \
    --home "$HOME" \
    --xdg-config "$XDG_CONFIG_HOME" \
    --fs-root "$MAHO_FS_ROOT" >/dev/null 2>&1; then
    fail "external persistence baseline was trusted"
fi
python "$PROBE" persistence baseline-set latest \
    --state-root "$PERSIST_STATE" \
    --home "$HOME" \
    --xdg-config "$XDG_CONFIG_HOME" \
    --fs-root "$MAHO_FS_ROOT" >/dev/null
python "$PROBE" persistence check \
    --state-root "$PERSIST_STATE" \
    --home "$HOME" \
    --xdg-config "$XDG_CONFIG_HOME" \
    --fs-root "$MAHO_FS_ROOT" |
python -c 'import json,sys; assert json.load(sys.stdin)["result"] == "clean"'
echo "PASS"

echo "=== exact verified Maho user-unit wiring is expected drift ==="
python - "$ROOT" "$XDG_DATA_HOME" <<'PY_MAHO_RUNTIME'
import json, os, pathlib, sys
root=pathlib.Path(sys.argv[1]); data=pathlib.Path(sys.argv[2])
sys.path.insert(0,str(root/'lib'))
from maho_runtime_release import _payload_hash
runtime=data/'maho/runtime'; releases=runtime/'releases'; releases.mkdir(parents=True)
stage=releases/'.fixture'; (stage/'systemd/user').mkdir(parents=True); (stage/'share/maho').mkdir(parents=True)
for name in ('maho-adaptive.service','maho-observe.service','maho-shell.service'):
    (stage/'systemd/user'/name).write_text('[Service]\nExecStart=true\n')
revision='a'*40; (stage/'share/maho/runtime-source-revision').write_text(revision+'\n')
digest=_payload_hash(stage); release=releases/digest; stage.rename(release)
(release/'manifest.json').write_text(json.dumps({'version':3,'content_sha256':digest,'source_revision':revision,'installed_at':'fixture'},sort_keys=True)+'\n')
for path in sorted(release.rglob('*'), key=lambda p: len(p.parts), reverse=True):
    os.chmod(path,0o555 if path.is_dir() else 0o444)
os.chmod(release,0o555)
(runtime/'current').symlink_to(release)
PY_MAHO_RUNTIME
ln -s "$XDG_DATA_HOME/maho/runtime/current/systemd/user/maho-adaptive.service" "$XDG_CONFIG_HOME/systemd/user/maho-adaptive.service"
MAHO_EXPECTED="$(python "$PROBE" persistence check --state-root "$PERSIST_STATE" --home "$HOME" --xdg-config "$XDG_CONFIG_HOME" --fs-root "$MAHO_FS_ROOT")"
python - "$MAHO_EXPECTED" <<'PY_EXPECTED'
import json,sys
r=json.loads(sys.argv[1])
assert r['result']=='changed',r
assert r['attention_result']=='clean',r
assert len(r['expected_changes'])==1,r
assert not r['unexpected_added'] and not r['unexpected_removed'] and not r['unexpected_changed'],r
item=r['expected_changes'][0]
assert item['path'].endswith('/maho-adaptive.service'),item
assert item['attribution']['classification']=='expected-maho-unit',item
assert item['attribution']['owner']=='maho-runtime',item
PY_EXPECTED
bash "$ROOT/bin/maho-security" persistence check >/dev/null
python - "$XDG_STATE_HOME/maho/history/events.jsonl" <<'PY_EXPECTED_EVENT'
import json,sys
from pathlib import Path
row=json.loads(Path(sys.argv[1]).read_text().splitlines()[-1])
assert row['kind']=='persistence.expected-transition',row
assert row['risk']=='info' and row['status']=='verified',row
PY_EXPECTED_EVENT
rm -f "$XDG_CONFIG_HOME/systemd/user/maho-adaptive.service"

echo "=== only declared Maho core enablement is expected ==="
mkdir -p "$XDG_CONFIG_HOME/systemd/user/default.target.wants"
ln -s "$XDG_CONFIG_HOME/systemd/user/maho-observe.service" "$XDG_CONFIG_HOME/systemd/user/default.target.wants/maho-observe.service"
ln -s "$XDG_DATA_HOME/maho/runtime/current/systemd/user/maho-observe.service" "$XDG_CONFIG_HOME/systemd/user/maho-observe.service"
CORE_EXPECTED="$(python "$PROBE" persistence check --state-root "$PERSIST_STATE" --home "$HOME" --xdg-config "$XDG_CONFIG_HOME" --fs-root "$MAHO_FS_ROOT")"
python - "$CORE_EXPECTED" <<'PY_CORE_EXPECTED'
import json,sys
r=json.loads(sys.argv[1])
classes={x.get('attribution',{}).get('classification') for x in r['expected_changes']}
assert 'expected-maho-unit' in classes,r
assert 'expected-maho-enable' in classes,r
assert r['attention_result']=='clean',r
PY_CORE_EXPECTED
rm -f "$XDG_CONFIG_HOME/systemd/user/default.target.wants/maho-observe.service" "$XDG_CONFIG_HOME/systemd/user/maho-observe.service"

echo "=== enabling a non-core Maho unit is still unexpected ==="
ln -s "$XDG_DATA_HOME/maho/runtime/current/systemd/user/maho-shell.service" "$XDG_CONFIG_HOME/systemd/user/maho-shell.service"
ln -s "$XDG_CONFIG_HOME/systemd/user/maho-shell.service" "$XDG_CONFIG_HOME/systemd/user/default.target.wants/maho-shell.service"
NONCORE="$(python "$PROBE" persistence check --state-root "$PERSIST_STATE" --home "$HOME" --xdg-config "$XDG_CONFIG_HOME" --fs-root "$MAHO_FS_ROOT")"
python - "$NONCORE" <<'PY_NONCORE'
import json,sys
r=json.loads(sys.argv[1])
assert r['attention_result']=='changed',r
paths={x['path'] for x in r['unexpected_added']}
assert any(p.endswith('/default.target.wants/maho-shell.service') for p in paths),r
assert any(x.get('path','').endswith('/maho-shell.service') for x in r['expected_changes']),r
PY_NONCORE
bash "$ROOT/bin/maho-security" persistence check >/dev/null
python - "$XDG_STATE_HOME/maho/history/events.jsonl" <<'PY_NONCORE_EVENT'
import json,sys
from pathlib import Path
row=json.loads(Path(sys.argv[1]).read_text().splitlines()[-1])
assert row['kind']=='persistence.changed',row
assert row['risk']=='medium' and row['status']=='observed',row
PY_NONCORE_EVENT
rm -f "$XDG_CONFIG_HOME/systemd/user/default.target.wants/maho-shell.service" "$XDG_CONFIG_HOME/systemd/user/maho-shell.service"
chmod -R u+w "$XDG_DATA_HOME/maho/runtime/releases"
echo "PASS"

echo "=== new persistence is detected as drift ==="
printf '[Desktop Entry]\nType=Application\nName=New\nExec=true\n' > "$XDG_CONFIG_HOME/autostart/new.desktop"
python "$PROBE" persistence check \
    --state-root "$PERSIST_STATE" \
    --home "$HOME" \
    --xdg-config "$XDG_CONFIG_HOME" \
    --fs-root "$MAHO_FS_ROOT" |
python -c '
import json,sys
r=json.load(sys.stdin)
assert r["result"] == "changed"
assert r["attention_result"] == "changed"
assert len(r["added"]) == 1
assert len(r["unexpected_added"]) == 1
assert not r["expected_changes"]
assert r["added"][0]["path"].endswith("new.desktop")
'
echo "PASS"

echo "=== persistence returns clean after drift is removed ==="
rm -f "$XDG_CONFIG_HOME/autostart/new.desktop"
python "$PROBE" persistence check \
    --state-root "$PERSIST_STATE" \
    --home "$HOME" \
    --xdg-config "$XDG_CONFIG_HOME" \
    --fs-root "$MAHO_FS_ROOT" |
python -c 'import json,sys; r=json.load(sys.stdin); assert r["result"] == "clean" and not r["added"] and not r["removed"] and not r["changed"], r'
echo "PASS"

echo "ALL SECURITY PROBE CONTRACTS PASS"
