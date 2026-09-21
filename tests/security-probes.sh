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

echo "=== persistence baseline requires exact deliberate authority ==="
SNAP_STATE="$(python - "$SNAPSHOT" <<'PY_SNAPSHOT_STATE'
import json,sys
print(json.load(open(sys.argv[1]))['state_sha256'])
PY_SNAPSHOT_STATE
)"
cp "$SNAPSHOT" "$TMP/external.json"
if python "$PROBE" persistence baseline-set "$TMP/external.json" --accept-state "$SNAP_STATE" --reason 'external copy' \
    --state-root "$PERSIST_STATE" --home "$HOME" --xdg-config "$XDG_CONFIG_HOME" --fs-root "$MAHO_FS_ROOT" >/dev/null 2>&1; then
    fail "external persistence baseline was trusted"
fi
if python "$PROBE" persistence baseline-set latest \
    --state-root "$PERSIST_STATE" --home "$HOME" --xdg-config "$XDG_CONFIG_HOME" --fs-root "$MAHO_FS_ROOT" >/dev/null 2>&1; then
    fail "baseline was accepted without exact state authority"
fi
if python "$PROBE" persistence baseline-set latest --accept-state "$(printf '0%.0s' {1..64})" --reason 'wrong state' \
    --state-root "$PERSIST_STATE" --home "$HOME" --xdg-config "$XDG_CONFIG_HOME" --fs-root "$MAHO_FS_ROOT" >/dev/null 2>&1; then
    fail "baseline was accepted with the wrong state hash"
fi
if python "$PROBE" persistence baseline-set latest --accept-state "$SNAP_STATE" \
    --state-root "$PERSIST_STATE" --home "$HOME" --xdg-config "$XDG_CONFIG_HOME" --fs-root "$MAHO_FS_ROOT" >/dev/null 2>&1; then
    fail "baseline was accepted without a reason"
fi
printf '[Desktop Entry]\nType=Application\nName=Stale\nExec=true\n' > "$XDG_CONFIG_HOME/autostart/stale.desktop"
if python "$PROBE" persistence baseline-set latest --accept-state "$SNAP_STATE" --reason 'stale fixture' \
    --state-root "$PERSIST_STATE" --home "$HOME" --xdg-config "$XDG_CONFIG_HOME" --fs-root "$MAHO_FS_ROOT" >/dev/null 2>&1; then
    fail "stale persistence snapshot was accepted after live state changed"
fi
rm -f "$XDG_CONFIG_HOME/autostart/stale.desktop"
BASELINE_SET="$(python "$PROBE" persistence baseline-set latest --accept-state "$SNAP_STATE" --reason 'fixture exact accepted persistence state' \
    --state-root "$PERSIST_STATE" --home "$HOME" --xdg-config "$XDG_CONFIG_HOME" --fs-root "$MAHO_FS_ROOT")"
python - "$BASELINE_SET" "$PERSIST_STATE" "$SNAP_STATE" <<'PY_BASELINE_AUTHORITY'
import json, pathlib, sys
r=json.loads(sys.argv[1]); root=pathlib.Path(sys.argv[2])/'persistence'; state=sys.argv[3]
assert r['result']=='baseline-set',r
assert r['state_sha256']==state,r
assert r['authority_id'].startswith('pba-'),r
baseline=json.loads((root/'baseline.json').read_text())
authority_id=baseline['baseline_authority_id']
history=root/'authorities'/f"{authority_id}.json"
assert history.is_file(),history
authority=json.loads(history.read_text())
assert baseline['state_sha256']==state,baseline
assert authority_id==authority['authority_id'],(baseline,authority)
assert authority['accepted_state_sha256']==state,authority
assert authority['reason']=='fixture exact accepted persistence state',authority
assert oct(history.stat().st_mode & 0o777)=='0o600'
assert not (root/'baseline-authority.json').exists(), 'duplicate baseline authority state must not exist'
PY_BASELINE_AUTHORITY
python "$PROBE" persistence baseline-show \
    --state-root "$PERSIST_STATE" --home "$HOME" --xdg-config "$XDG_CONFIG_HOME" --fs-root "$MAHO_FS_ROOT" |
python -c 'import json,sys; r=json.load(sys.stdin); assert r["result"]=="baseline" and r["authority_id"].startswith("pba-"),r'
python "$PROBE" persistence check \
    --state-root "$PERSIST_STATE" --home "$HOME" --xdg-config "$XDG_CONFIG_HOME" --fs-root "$MAHO_FS_ROOT" |
python -c 'import json,sys; r=json.load(sys.stdin); assert r["result"]=="clean" and r["baseline_authority_id"].startswith("pba-"),r'
AUTHORITY_PATH="$(python - "$PERSIST_STATE/persistence/baseline.json" "$PERSIST_STATE/persistence/authorities" <<'PY_AUTH_PATH'
import json,sys
from pathlib import Path
b=json.load(open(sys.argv[1])); print(Path(sys.argv[2])/f"{b['baseline_authority_id']}.json")
PY_AUTH_PATH
)"
cp "$AUTHORITY_PATH" "$TMP/baseline-authority.good.json"
python - "$AUTHORITY_PATH" <<'PY_TAMPER_AUTHORITY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]); r=json.loads(p.read_text()); r['reason']='tampered'; p.write_text(json.dumps(r,sort_keys=True)+'\n')
PY_TAMPER_AUTHORITY
python "$PROBE" persistence check \
    --state-root "$PERSIST_STATE" --home "$HOME" --xdg-config "$XDG_CONFIG_HOME" --fs-root "$MAHO_FS_ROOT" |
python -c 'import json,sys; r=json.load(sys.stdin); assert r["result"]=="unavailable" and r["reason"]=="baseline-authority-invalid",r'
cp "$TMP/baseline-authority.good.json" "$AUTHORITY_PATH"
chmod 600 "$AUTHORITY_PATH"
echo "PASS"

echo "=== package-declared system enablement is attributed narrowly ==="
mkdir -p \
    "$MAHO_PACMAN_DB_ROOT/gpu-utils-1.0-1" \
    "$MAHO_FS_ROOT/usr/lib/systemd/system" \
    "$MAHO_FS_ROOT/etc/systemd/system/sleep.target.wants" \
    "$MAHO_FS_ROOT/etc/systemd/system/multi-user.target.wants"
printf '[Service]\nExecStart=/usr/bin/true\n' > "$MAHO_FS_ROOT/usr/lib/systemd/system/gpu-sleep.service"
printf '[Service]\nExecStart=/usr/bin/true\n' > "$MAHO_FS_ROOT/usr/lib/systemd/system/gpu-power.service"
SLEEP_SHA="$(sha256sum "$MAHO_FS_ROOT/usr/lib/systemd/system/gpu-sleep.service" | awk '{print $1}')"
POWER_SHA="$(sha256sum "$MAHO_FS_ROOT/usr/lib/systemd/system/gpu-power.service" | awk '{print $1}')"
cat > "$MAHO_PACMAN_DB_ROOT/gpu-utils-1.0-1/desc" <<'EOF_GPU_DESC'
%NAME%
gpu-utils

%VERSION%
1.0-1

EOF_GPU_DESC
cat > "$MAHO_PACMAN_DB_ROOT/gpu-utils-1.0-1/install" <<'EOF_GPU_INSTALL'
post_install() {
  systemctl enable gpu-sleep
}
post_upgrade() {
  systemctl enable $service
}
EOF_GPU_INSTALL
python - "$MAHO_PACMAN_DB_ROOT/gpu-utils-1.0-1/mtree" "$SLEEP_SHA" "$POWER_SHA" <<'PY_GPU_MTREE'
import gzip,sys
path,sleep_sha,power_sha=sys.argv[1:]
with gzip.open(path,'wt') as f:
    f.write(f'''#mtree
./usr/lib/systemd/system/gpu-sleep.service type=file sha256digest={sleep_sha}
./usr/lib/systemd/system/gpu-power.service type=file sha256digest={power_sha}
''')
PY_GPU_MTREE
ln -s /usr/lib/systemd/system/gpu-sleep.service "$MAHO_FS_ROOT/etc/systemd/system/sleep.target.wants/gpu-sleep.service"
ln -s /usr/lib/systemd/system/gpu-power.service "$MAHO_FS_ROOT/etc/systemd/system/multi-user.target.wants/gpu-power.service"
PACKAGE_EXPECTED="$(python "$PROBE" persistence check --state-root "$PERSIST_STATE" --home "$HOME" --xdg-config "$XDG_CONFIG_HOME" --fs-root "$MAHO_FS_ROOT" --db-root "$MAHO_PACMAN_DB_ROOT")"
python - "$PACKAGE_EXPECTED" <<'PY_PACKAGE_EXPECTED'
import json,sys
r=json.loads(sys.argv[1])
expected=[x for x in r['expected_changes'] if x.get('attribution',{}).get('classification')=='expected-package-enable']
assert len(expected)==1,r
assert expected[0]['path'].endswith('/gpu-sleep.service'),expected
assert expected[0]['attribution']['owner']=='gpu-utils',expected
unexpected={x['path'] for x in r['unexpected_added']}
assert any(x.endswith('/gpu-power.service') for x in unexpected),r
assert not any(x.endswith('/gpu-sleep.service') for x in unexpected),r
assert r['attention_result']=='changed',r
PY_PACKAGE_EXPECTED
rm -f \
    "$MAHO_FS_ROOT/etc/systemd/system/sleep.target.wants/gpu-sleep.service" \
    "$MAHO_FS_ROOT/etc/systemd/system/multi-user.target.wants/gpu-power.service"
echo "PASS"

echo "=== exact verified Maho user-unit wiring is expected drift ==="
python - "$ROOT" "$XDG_DATA_HOME" <<'PY_MAHO_RUNTIME'
import json, os, pathlib, sys
root=pathlib.Path(sys.argv[1]); data=pathlib.Path(sys.argv[2])
sys.path.insert(0,str(root/'lib'))
from maho_runtime_release import _payload_hash
runtime=data/'maho/runtime'; releases=runtime/'releases'; releases.mkdir(parents=True)
stage=releases/'.fixture'; (stage/'systemd/user').mkdir(parents=True); (stage/'share/maho').mkdir(parents=True)
for name in ('maho-adaptive.service','maho-observe.service','maho-shell.service','maho-kbdlight.service'):
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

echo "=== canonical kbdlight unit and enablement are exact expected Maho wiring ==="
ln -s "$XDG_DATA_HOME/maho/runtime/current/systemd/user/maho-kbdlight.service" "$XDG_CONFIG_HOME/systemd/user/maho-kbdlight.service"
ln -s "$XDG_CONFIG_HOME/systemd/user/maho-kbdlight.service" "$XDG_CONFIG_HOME/systemd/user/default.target.wants/maho-kbdlight.service"
KBD_EXPECTED="$(python "$PROBE" persistence check --state-root "$PERSIST_STATE" --home "$HOME" --xdg-config "$XDG_CONFIG_HOME" --fs-root "$MAHO_FS_ROOT")"
python - "$KBD_EXPECTED" <<'PY_KBD_EXPECTED'
import json,sys
r=json.loads(sys.argv[1])
matches=[x for x in r['expected_changes'] if x.get('path','').endswith('/maho-kbdlight.service')]
assert len(matches)==2,r
assert {x['attribution']['classification'] for x in matches}=={'expected-maho-unit','expected-maho-enable'},matches
assert r['attention_result']=='clean',r
PY_KBD_EXPECTED
rm -f "$XDG_CONFIG_HOME/systemd/user/maho-kbdlight.service"
cp "$XDG_DATA_HOME/maho/runtime/current/systemd/user/maho-kbdlight.service" "$XDG_CONFIG_HOME/systemd/user/maho-kbdlight.service"
KBD_TAMPERED="$(python "$PROBE" persistence check --state-root "$PERSIST_STATE" --home "$HOME" --xdg-config "$XDG_CONFIG_HOME" --fs-root "$MAHO_FS_ROOT")"
python - "$KBD_TAMPERED" <<'PY_KBD_TAMPERED'
import json,sys
r=json.loads(sys.argv[1])
assert r['attention_result']=='changed',r
paths={x['path'] for x in r['unexpected_added']}
assert any(x.endswith('/maho-kbdlight.service') for x in paths),r
PY_KBD_TAMPERED
rm -f "$XDG_CONFIG_HOME/systemd/user/default.target.wants/maho-kbdlight.service" "$XDG_CONFIG_HOME/systemd/user/maho-kbdlight.service"
echo "PASS"

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
