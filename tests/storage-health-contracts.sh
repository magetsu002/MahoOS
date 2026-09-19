#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT
mkdir -p "$TMP/bin"
cat > "$TMP/bin/btrfs" <<'EOF'
#!/usr/bin/env bash
[ "$*" = 'device stats -c /' ] || exit 90
printf '[/dev/nvme0n1p2].write_io_errs    0\n'
EOF
cat > "$TMP/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
[ "$1 $2" = 'show maho-btrfs-scrub-root.service' ] || exit 90
printf 'Result=success\nExecMainStatus=0\nInactiveExitTimestamp=fixture\n'
EOF
cat > "$TMP/bin/nvme" <<'EOF'
#!/usr/bin/env bash
[ "$*" = 'list -o json' ] || exit 90
printf '{"Devices":[{"DevicePath":"/dev/nvme0n1"}]}\n'
EOF
chmod +x "$TMP/bin/"*
OUT="$(PATH="$TMP/bin:/usr/bin:/bin" MAHO_ROOT="$ROOT" "$ROOT/bin/maho-storage-health")"
python - "$OUT" <<'PY'
import json,sys
r=json.loads(sys.argv[1])
assert r['read_only'] is True,r
assert r['assessment']=='observed',r
assert all(v != 'unavailable' for v in r['coverage'].values()),r
assert r['scrub']['service']['Result']=='success',r
assert r['nvme']['inventory']['Devices'][0]['DevicePath']=='/dev/nvme0n1',r
assert 'diagnostic' in r['trust_note'],r
PY
cat > "$TMP/bin/nvme" <<'EOF'
#!/usr/bin/env bash
exit 127
EOF
chmod +x "$TMP/bin/nvme"
OUT="$(PATH="$TMP/bin:/usr/bin:/bin" MAHO_ROOT="$ROOT" "$ROOT/bin/maho-storage-health")"
python - "$OUT" <<'PY'
import json,sys
r=json.loads(sys.argv[1])
assert r['assessment']=='partial',r
assert r['coverage']['nvme_inventory']=='unavailable',r
PY
echo 'ALL STORAGE HEALTH CONTRACTS PASS'
