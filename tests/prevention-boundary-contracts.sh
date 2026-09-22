#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT

clang -O2 -g -target bpf -D__TARGET_ARCH_x86 \
  -I"/usr/include/$(gcc -dumpmachine)" -I"$ROOT/bpf" \
  -c "$ROOT/bpf/maho_prevention.bpf.c" -o "$BUILD/maho_prevention.bpf.o"
gcc -O2 -Wall -Wextra -Werror "$ROOT/src/maho_prevention_loader.c" \
  -o "$BUILD/maho-prevention-loader" $(pkg-config --cflags --libs libbpf)
gcc -O2 -Wall -Wextra -Werror "$ROOT/src/maho_prevention_evidence.c" \
  -o "$BUILD/maho-prevention-evidence" $(pkg-config --cflags --libs libbpf)

for section in file_open inode_create inode_mkdir inode_mknod inode_unlink inode_rmdir inode_symlink inode_link inode_rename inode_setattr sb_mount task_kill; do
  llvm-objdump -h "$BUILD/maho_prevention.bpf.o" | grep -Fq "lsm/$section" || {
    echo "FAIL missing BPF LSM hook $section" >&2
    exit 1
  }
done
grep -Fq 'bpf_get_current_task_btf' "$ROOT/bpf/maho_prevention.bpf.c"
grep -Fq 'start_boottime' "$ROOT/bpf/maho_prevention.bpf.c"
grep -Fq 'executable_ino' "$ROOT/bpf/maho_prevention.bpf.c"
grep -Fq 'bpf_ktime_get_boot_ns() >= value->expires_boot_ns' "$ROOT/bpf/maho_prevention.bpf.c"
grep -Fq 'BPF_MAP_TYPE_RINGBUF' "$ROOT/bpf/maho_prevention.bpf.c"
grep -Fq 'protected_devices' "$ROOT/bpf/maho_prevention.bpf.c"
grep -Fq 'protected_processes' "$ROOT/bpf/maho_prevention.bpf.c"
grep -Fq 'process_control_authorities' "$ROOT/bpf/maho_prevention.bpf.c"
grep -Fq 'process_key_from_task' "$ROOT/bpf/maho_prevention.bpf.c"
grep -Fq 'i_rdev' "$ROOT/bpf/maho_prevention.bpf.c"
grep -Fq 'host_mutation_performed' "$ROOT/src/maho_prevention_evidence.c"
grep -Fq 'compromise_evidence' "$ROOT/src/maho_prevention_evidence.c"
if grep -Eiq 'command.*(rm|mkfs)|argv.*(rm|mkfs)' "$ROOT/bpf/maho_prevention.bpf.c"; then
  echo 'FAIL enforcement contains a command-name blacklist' >&2
  exit 1
fi
echo 'PASS BPF mutation boundary builds with exact identity, expiry, evidence, and required hooks'
