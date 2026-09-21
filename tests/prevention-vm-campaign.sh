#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
cleanup() { rm -r -- "$WORK"; }
trap cleanup EXIT
GUEST="$WORK/root"
mkdir -p "$GUEST"/{bin,dev,etc,lib64,proc,sys,usr/bin,usr/lib,usr/lib/python3.14,var/lib/maho/prevention,ordinary,protected}

clang -O2 -g -target bpf -D__TARGET_ARCH_x86 -I"/usr/include/$(gcc -dumpmachine)" -I"$ROOT/bpf" \
  -c "$ROOT/bpf/maho_prevention.bpf.c" -o "$GUEST/maho_prevention.bpf.o"
gcc -O2 "$ROOT/src/maho_prevention_loader.c" -o "$GUEST/bin/loader" $(pkg-config --cflags --libs libbpf)
gcc -O2 "$ROOT/src/maho_prevention_evidence.c" -o "$GUEST/bin/evidence" $(pkg-config --cflags --libs libbpf)
gcc -O2 -static -I"$ROOT/bpf" "$ROOT/tests/fixtures/prevention-vm-helper.c" -o "$GUEST/bin/helper"
cp "$GUEST/bin/helper" "$GUEST/bin/opaque"
cp /usr/lib/initcpio/busybox "$GUEST/bin/busybox"
for applet in sh cat mkdir poweroff sleep grep kill; do ln -s busybox "$GUEST/bin/$applet"; done
cp "$ROOT/tests/fixtures/prevention-vm-init" "$GUEST/init"
cp "$ROOT/tests/fixtures/prevention-vm-payload.py" "$GUEST/payload.py"
chmod 0755 "$GUEST/init"

copy_deps() {
  local binary="$1" dependency destination
  while read -r dependency; do
    [ -n "$dependency" ] || continue
    destination="$GUEST$dependency"
    mkdir -p "$(dirname "$destination")"
    cp -L "$dependency" "$destination"
  done < <(ldd "$binary" | awk '/=> \// {print $3} /^\// {print $1}')
}
for binary in "$GUEST/bin/loader" "$GUEST/bin/evidence" "$GUEST/bin/busybox" /usr/bin/python; do copy_deps "$binary"; done
cp -L /lib64/ld-linux-x86-64.so.2 "$GUEST/lib64/ld-linux-x86-64.so.2"
cp /usr/bin/python "$GUEST/usr/bin/python"
cp -L /usr/lib/libpython3.14.so.1.0 "$GUEST/usr/lib/libpython3.14.so.1.0"
cp -a /usr/lib/python3.14/encodings "$GUEST/usr/lib/python3.14/encodings"
cp /usr/lib/python3.14/codecs.py "$GUEST/usr/lib/python3.14/codecs.py"

(cd "$GUEST" && find . -print0 | sort -z | cpio --null -o --format=newc --quiet | gzip -1 > "$WORK/initramfs.img")
truncate -s 8M "$WORK/device.img"
KERNEL="${MAHO_PREVENTION_VM_KERNEL:-/boot/vmlinuz-linux-cachyos}"
[ -r "$KERNEL" ] || { echo "VM kernel unavailable: $KERNEL" >&2; exit 2; }
set +e
timeout 90 qemu-system-x86_64 -nodefaults -no-reboot -nographic -serial stdio \
  -m 768 -kernel "$KERNEL" -initrd "$WORK/initramfs.img" \
  -drive file="$WORK/device.img",format=raw,if=virtio \
  -append 'console=ttyS0 rdinit=/init panic=-1 lsm=landlock,lockdown,yama,integrity,bpf' \
  > "$WORK/serial.log" 2>&1
qemu_status=$?
set -e
cat "$WORK/serial.log"
grep -Fq MAHO_PREVENTION_VM_COMPLETE "$WORK/serial.log" || { echo "FAIL hostile VM campaign incomplete (qemu=$qemu_status)" >&2; exit 1; }
if grep -Fq MAHO_PREVENTION_FAIL "$WORK/serial.log"; then exit 1; fi
required=(
  boundary-active-after-loader-exit ordinary-write helper-denied python-denied opaque-denied
  device-alias-denied exact-device-authority
  exact-authority expired-write-denied wrong-start-write-denied scope-escape-denied
  unlink-denied chmod-denied rename-denied hardlink-denied symlink-denied
  bind-alias-denied namespace-denied ordinary-churn durable-evidence
)
for marker in "${required[@]}"; do grep -Fq "MAHO_PREVENTION_PASS:$marker" "$WORK/serial.log" || { echo "FAIL missing VM marker $marker" >&2; exit 1; }; done
python - "$WORK/serial.log" <<'PY'
from pathlib import Path
import re, statistics, sys
values=[int(x) for x in re.findall(r'MAHO_PREVENTION_BENCH_NS:(\d+)',Path(sys.argv[1]).read_text(errors='replace'))]
assert len(values) == 2, values
ratio=values[1]/max(values[0],1)
print(f'MAHO_PREVENTION_PERFORMANCE before_ns={values[0]} after_ns={values[1]} ratio={ratio:.3f}')
assert ratio < 2.0, ratio
PY
echo 'ALL HOSTILE MAHO PREVENTION VM SCENARIOS PASS'
