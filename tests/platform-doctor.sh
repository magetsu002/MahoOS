#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/etc/snapper/configs"
LOG="$TMP/read-only.log"
: >"$LOG"
export MAHO_TEST_PLATFORM_LOG="$LOG"

cat >"$TMP/bin/pacman" <<'EOF_PACMAN'
#!/usr/bin/env bash
printf 'pacman\t%s\n' "$*" >>"$MAHO_TEST_PLATFORM_LOG"
[ "${1:-}" = -Q ] || { echo "unexpected pacman operation: $*" >&2; exit 99; }
case "${2:-}" in
  linux-cachyos|linux-cachyos-lts|snapper|snap-pac|limine|limine-snapper-sync) exit 0 ;;
  *) exit 1 ;;
esac
EOF_PACMAN

cat >"$TMP/bin/findmnt" <<'EOF_FINDMNT'
#!/usr/bin/env bash
printf 'findmnt\t%s\n' "$*" >>"$MAHO_TEST_PLATFORM_LOG"
field=''
target=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    -n) shift ;;
    -o) field="$2"; shift 2 ;;
    *) target="$1"; shift ;;
  esac
done
case "$field:$target" in
  FSTYPE:/) printf 'btrfs\n' ;;
  SOURCE:/) printf '/dev/mapper/maho-root\n' ;;
  FSROOT:/) printf '/@\n' ;;
  SOURCE:/home) printf '/dev/mapper/maho-root\n' ;;
  FSROOT:/home) printf '/@home\n' ;;
  FSTYPE:/boot) printf 'vfat\n' ;;
  SOURCE:/boot) printf '/dev/nvme0n1p1\n' ;;
  *) exit 1 ;;
esac
EOF_FINDMNT

cat >"$TMP/bin/snapper" <<'EOF_SNAPPER'
#!/usr/bin/env bash
printf 'snapper\t%s\n' "$*" >>"$MAHO_TEST_PLATFORM_LOG"
[ "$*" = '--jsonout --config root get-config' ] || { echo "unexpected snapper operation: $*" >&2; exit 99; }
printf '{"config":{"SUBVOLUME":"/"}}\n'
EOF_SNAPPER
chmod +x "$TMP/bin/pacman" "$TMP/bin/findmnt" "$TMP/bin/snapper"
# Deliberately leave MAHO_SNAPPER_ROOT_CONFIG unreadable/missing: status must
# prefer Snapper's own read-only API, matching the live ALLOW_USERS setup.

export PATH="$TMP/bin:/usr/bin:/bin"
export MAHO_ROOT="$ROOT"
export MAHO_SNAPPER_ROOT_CONFIG="$TMP/etc/snapper/configs/root"

json="$(bash "$ROOT/bin/maho-platform" status --json)"
python - "$json" <<'PY'
import json
import sys

data = json.loads(sys.argv[1])
assert data['schema_version'] == 1
assert data['policy']['primary_kernel'] == 'linux-cachyos'
assert data['policy']['fallback_kernel'] == 'linux-cachyos-lts'
assert data['policy']['fallback_visibility'] == 'recovery-or-advanced-only'
x = data['detected']
assert x['root_fstype'] == 'btrfs'
assert x['root_source'] == '/dev/mapper/maho-root'
assert x['root_fsroot'] == '/@'
assert x['home_source'] == '/dev/mapper/maho-root'
assert x['home_fsroot'] == '/@home'
assert x['home_separate_from_root'] is True
assert x['boot_fstype'] == 'vfat'
assert x['boot_source'] == '/dev/nvme0n1p1'
for key in ('linux_cachyos', 'linux_cachyos_lts', 'snapper', 'snap_pac', 'limine', 'limine_snapper_sync'):
    assert x[key] == 'installed', (key, x[key])
assert x['root_snapper_config'] == 'present'
PY
echo 'PASS platform status detects the intended V1 recovery topology'

bash "$ROOT/bin/maho-platform" doctor >"$TMP/doctor.out"
grep -Fq 'PASS  Btrfs root' "$TMP/doctor.out"
grep -Fq 'PASS  home rollback isolation' "$TMP/doctor.out"
grep -Fq 'PASS  primary kernel' "$TMP/doctor.out"
grep -Fq 'PASS  LTS fallback' "$TMP/doctor.out"
grep -Fq '/boot state must be transactionally coherent with root' "$TMP/doctor.out"
echo 'PASS platform doctor distinguishes root snapshots from boot state'

cat >"$TMP/kernel-failure.json" <<'EOF_FAILURE'
{
  "failure": {"domain": "kernel", "graphical_available": false},
  "availability": {"lts_kernel": true}
}
EOF_FAILURE
plan="$(bash "$ROOT/bin/maho-platform" plan "$TMP/kernel-failure.json")"
python - "$plan" <<'PY'
import json
import sys

d = json.loads(sys.argv[1])
assert d['action'] == 'boot-lts-kernel'
assert d['requires_confirmation'] is True
assert d['automatic_allowed'] is False
assert d['scope'] == 'kernel'
PY
echo 'PASS platform recovery planning remains consent-gated and non-mutating'

# Only read-only probes are allowed. The fake pacman exits 99 for any operation
# other than -Q, so reaching here also proves no install/remove/update was tried.
[ "$(grep -c '^pacman' "$LOG")" -eq 12 ] || {
  echo 'FAIL unexpected package probe count' >&2
  cat "$LOG" >&2
  exit 1
}
if grep -Ev $'^(pacman\t-Q |findmnt\t-n -o |snapper\t--jsonout --config root get-config$)' "$LOG" | grep -q .; then
  echo 'FAIL platform doctor attempted an unexpected external operation' >&2
  cat "$LOG" >&2
  exit 1
fi
[ "$(grep -c $'^snapper\t--jsonout --config root get-config$' "$LOG")" -ge 2 ] || {
  echo 'FAIL platform status did not use Snapper read-only config API' >&2
  cat "$LOG" >&2
  exit 1
}
echo 'PASS platform status uses Snapper read-only config API when direct config files are inaccessible'
echo 'PASS platform doctor issued read-only package, mount, and Snapper probes only'
echo 'ALL PLATFORM DOCTOR CONTRACTS PASS'
