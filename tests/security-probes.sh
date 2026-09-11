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
export MAHO_FS_ROOT="$TMP/fs"
export MAHO_PROC_ROOT="$TMP/proc"

mkdir -p \
    "$HOME" \
    "$XDG_STATE_HOME" \
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
assert len(r["added"]) == 1
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
