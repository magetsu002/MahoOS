#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ] || [[ "$1" != /dev/vd? ]]; then
  echo "usage: installer-storage-integration.sh /dev/vdX" >&2
  exit 2
fi
if [ "$(id -u)" -ne 0 ]; then
  echo "integration test requires root inside a disposable VM" >&2
  exit 2
fi

target="$1"
serial="$(lsblk -dnro SERIAL "$target")"
if [[ "$serial" != MAHO-DISPOSABLE-* ]]; then
  echo "refusing non-disposable serial: $serial" >&2
  exit 2
fi

state=/run/maho-installer-storage-test
plan="$state/plan.json"
journal="$state/journal.json"
key="$state/key"
mount_root=/mnt/maho-installer-target
install -d -m 0700 "$state"
head -c 64 /dev/urandom > "$key"
chmod 0600 "$key"

maho-installer plan "$target" --output "$plan" --json > "$state/plan.stdout.json"
readarray -t authority < <(python - "$plan" <<'PY'
import json, sys
plan = json.load(open(sys.argv[1], encoding="utf-8"))
print(plan["plan_id"])
print(plan["destructive_confirmation"])
PY
)

maho-installer execute "$plan" \
  --plan-id "${authority[0]}" \
  --confirmation "${authority[1]}" \
  --journal "$journal" \
  --mount-root "$mount_root" \
  --key-file "$key" > "$state/execution.json"

mapper="$(python - "$plan" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["encryption_contract"]["mapper_name"])
PY
)"
partition1="${target}1"
partition2="${target}2"

test "$(blkid -s TYPE -o value "$partition1")" = vfat
test "$(blkid -s TYPE -o value "$partition2")" = crypto_LUKS
test "$(blkid -s TYPE -o value "/dev/mapper/$mapper")" = btrfs
test "$(findmnt -n -o TARGET --target "$mount_root/boot")" = "$mount_root/boot"
test "$(findmnt -n -o FSTYPE --target "$mount_root/boot")" = vfat
for subvolume in @ @home @snapshots @var_log; do
  btrfs subvolume list -a "$mount_root" | grep -Eq " path (<FS_TREE>/)?${subvolume}$"
done
test "$(python - "$journal" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["phase"])
PY
)" = MOUNTED

lsblk -o NAME,PATH,TYPE,SIZE,FSTYPE,PARTTYPE,PARTUUID,MOUNTPOINTS "$target"
blkid "$partition1" "$partition2" "/dev/mapper/$mapper"
echo "PASS disposable VM disk has exact MahoOS V1 storage architecture"
