#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "run-live-bakeoff-root.sh must be started once through pkexec" >&2
    exit 2
fi

CALLER_UID="${PKEXEC_UID:-}"
if [[ -z "$CALLER_UID" ]]; then
    echo "PKEXEC_UID is missing; refusing to guess the desktop user" >&2
    exit 2
fi

CALLER_NAME="$(getent passwd "$CALLER_UID" | cut -d: -f1)"
CALLER_HOME="$(getent passwd "$CALLER_UID" | cut -d: -f6)"
CALLER_GID="$(id -g "$CALLER_NAME")"

WORKTREE="$CALLER_HOME/Projects/Maho-OS-guardian-sensor-bakeoff"
HARNESS="$WORKTREE/tools/guardian-sensor-bakeoff"
CACHE="$CALLER_HOME/.cache/maho/guardian-sensor-bakeoff"

TETRAGON="$CACHE/candidates/tetragon-1.7.1/usr/local/bin/tetragon"
TETRAGON_BPF="$CACHE/candidates/tetragon-1.7.1/usr/local/lib/tetragon/bpf"
TRACEE="$CACHE/candidates/tracee-0.24.1/dist/tracee-static"
FALCO_BUILD="$CACHE/build/falco-libs-0.26.0"
SINSP="$FALCO_BUILD/libsinsp/examples/sinsp-example"
SCAP_OPEN="$FALCO_BUILD/libscap/examples/01-open/scap-open"
WORKLOAD="$HARNESS/workload.py"
PYTHON_REAL="$(readlink -f "$(command -v python3)")"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${1:-/tmp/maho-guardian-sensor-bakeoff-$STAMP}"
TRACEE_INSTALL="/tmp/maho-tracee-bakeoff-$STAMP"

for required in "$TETRAGON" "$TRACEE" "$SINSP" "$SCAP_OPEN" "$WORKLOAD"; do
    [[ -e "$required" ]] || {
        echo "missing prerequisite: $required" >&2
        exit 3
    }
done

install -d -m 0750 -o "$CALLER_UID" -g "$CALLER_GID" "$OUT"
ACTIVE_PIDS=()

cleanup() {
    local pid
    for pid in "${ACTIVE_PIDS[@]:-}"; do
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            kill -INT "$pid" 2>/dev/null || true
            sleep 0.2
            kill -TERM "$pid" 2>/dev/null || true
        fi
    done
    rm -rf -- "$TRACEE_INSTALL"
}
trap cleanup EXIT

sample_process() {
    local pid="$1" dest="$2"
    if kill -0 "$pid" 2>/dev/null; then
        ps -o pid=,ppid=,etimes=,%cpu=,rss=,vsz=,comm= -p "$pid" > "$dest" || true
    fi
}

stop_process() {
    local pid="$1"
    if kill -0 "$pid" 2>/dev/null; then
        kill -INT "$pid" 2>/dev/null || true
        for _ in {1..40}; do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.1
        done
    fi
    if kill -0 "$pid" 2>/dev/null; then
        kill -TERM "$pid" 2>/dev/null || true
        for _ in {1..20}; do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.1
        done
    fi
    if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid" 2>/dev/null || true
    fi
    wait "$pid" 2>/dev/null || true
}

start_gated_workload() {
    local tag="$1"
    local gate="$OUT/$tag.gate"
    local manifest="$OUT/$tag-manifest.json"
    local err="$OUT/$tag-workload.err"

    rm -f "$gate" "$manifest" "$err"

    setpriv \
        --reuid "$CALLER_UID" \
        --regid "$CALLER_GID" \
        --init-groups \
        --reset-env \
        /bin/sh -c '
            gate="$1"
            workload="$2"
            while [[ ! -e "$gate" ]]; do
                sleep 0.02
            done
            exec python3 "$workload"
        ' sh "$gate" "$WORKLOAD" >"$manifest" 2>"$err" &

    WORKLOAD_PID=$!
    WORKLOAD_GATE="$gate"
    ACTIVE_PIDS+=("$WORKLOAD_PID")
}

release_and_wait_workload() {
    touch "$WORKLOAD_GATE"
    chown "$CALLER_UID:$CALLER_GID" "$WORKLOAD_GATE"
    if ! wait "$WORKLOAD_PID"; then
        echo "workload failed; see manifest/stderr in $OUT" >&2
        return 1
    fi
}

write_tetragon_policy() {
    local pid="$1" dest="$2"
    cat >"$dest" <<EOF
apiVersion: cilium.io/v1alpha1
kind: TracingPolicy
metadata:
  name: maho-guardian-bakeoff
spec:
  kprobes:
  - call: "security_file_permission"
    syscall: false
    args:
    - index: 0
      type: "file"
    - index: 1
      type: "int"
    selectors:
    - matchBinaries:
      - operator: In
        values:
        - "$PYTHON_REAL"
        followChildren: true
  - call: "tcp_connect"
    syscall: false
    args:
    - index: 0
      type: "sock"
    selectors:
    - matchBinaries:
      - operator: In
        values:
        - "$PYTHON_REAL"
        followChildren: true
EOF
}

echo "Guardian sensor bake-off"
echo "output: $OUT"
echo "caller: $CALLER_NAME ($CALLER_UID)"
echo "privilege prompts: one (this process)"


echo
echo "== Tracee exact-tree capture =="
start_gated_workload tracee
TRACEE_ROOT_PID="$WORKLOAD_PID"
install -d -m 0777 "$TRACEE_INSTALL"

"$TRACEE" \
    --install-path "$TRACEE_INSTALL" \
    --scope "tree=$TRACEE_ROOT_PID" \
    --proctree source=events \
    -e sched_process_exec \
    -e sched_process_exit \
    -e openat \
    -e write \
    -e close \
    -e chmod \
    -e fchmod \
    -e fchmodat \
    -e rename \
    -e renameat \
    -e renameat2 \
    -e unlink \
    -e unlinkat \
    -e symlink \
    -e symlinkat \
    -e socket \
    -e bind \
    -e listen \
    -e connect \
    -e accept \
    --output "json:$OUT/tracee-events.jsonl" \
    --server "http-address=127.0.0.1:3367" \
    --server metrics \
    --log warn \
    >"$OUT/tracee.stdout" 2>"$OUT/tracee.stderr" &
TRACEE_PID=$!
ACTIVE_PIDS+=("$TRACEE_PID")

sleep 2
if ! kill -0 "$TRACEE_PID" 2>/dev/null; then
    echo "Tracee failed to start" >&2
    release_and_wait_workload || true
else
    sample_process "$TRACEE_PID" "$OUT/tracee-process-sample.txt"
    curl -fsS http://127.0.0.1:3367/metrics >"$OUT/tracee-metrics-before.txt" || true
    release_and_wait_workload
    sleep 1
    curl -fsS http://127.0.0.1:3367/metrics >"$OUT/tracee-metrics-after.txt" || true
    stop_process "$TRACEE_PID"
fi

echo
echo "== Tetragon exact-tree capture =="
start_gated_workload tetragon
TETRAGON_ROOT_PID="$WORKLOAD_PID"
TETRAGON_POLICY="$OUT/tetragon-policy.yaml"
write_tetragon_policy "$TETRAGON_ROOT_PID" "$TETRAGON_POLICY"

"$TETRAGON" \
    --bpf-lib "$TETRAGON_BPF" \
    --bpf-dir maho-guardian-bakeoff \
    --tracing-policy "$TETRAGON_POLICY" \
    --export-filename "$OUT/tetragon-events.jsonl" \
    --export-file-perm 600 \
    --export-file-max-size-mb 100 \
    --export-file-max-backups 1 \
    --server-address "" \
    --health-server-address "" \
    --metrics-server 127.0.0.1:2113 \
    --enable-k8s-api=false \
    --enable-cri=false \
    --enable-tracing-policy-crd=false \
    --log-level warn \
    --log-file "$OUT/tetragon.log" \
    >"$OUT/tetragon.stdout" 2>"$OUT/tetragon.stderr" &
TETRAGON_PID=$!
ACTIVE_PIDS+=("$TETRAGON_PID")

sleep 2
if ! kill -0 "$TETRAGON_PID" 2>/dev/null; then
    echo "Tetragon failed to start" >&2
    release_and_wait_workload || true
else
    sample_process "$TETRAGON_PID" "$OUT/tetragon-process-sample.txt"
    curl -fsS http://127.0.0.1:2113/metrics >"$OUT/tetragon-metrics-before.txt" || true
    release_and_wait_workload
    sleep 1
    curl -fsS http://127.0.0.1:2113/metrics >"$OUT/tetragon-metrics-after.txt" || true
    stop_process "$TETRAGON_PID"
fi


echo
echo "== Falco libs/libsinsp exact-tree capture =="
start_gated_workload falco
FALCO_ROOT_PID="$WORKLOAD_PID"
FALCO_FILTER="proc.pid=$FALCO_ROOT_PID or proc.apid=$FALCO_ROOT_PID"

"$SINSP" \
    --modern_bpf \
    --json \
    --filter "$FALCO_FILTER" \
    --output-fields "*%evt.num %evt.time %evt.category %proc.ppid %proc.pid %evt.type %proc.exe %proc.cmdline %evt.args %fd.name" \
    >"$OUT/falco-events.jsonl" 2>"$OUT/falco.stderr" &
FALCO_PID=$!
ACTIVE_PIDS+=("$FALCO_PID")

sleep 2
if ! kill -0 "$FALCO_PID" 2>/dev/null; then
    echo "Falco libsinsp failed to start" >&2
    release_and_wait_workload || true
else
    sample_process "$FALCO_PID" "$OUT/falco-process-sample.txt"
    release_and_wait_workload
    sleep 1
    stop_process "$FALCO_PID"
fi

echo
echo "== Falco libscap drop-accounting smoke =="
"$SCAP_OPEN" --modern_bpf >"$OUT/falco-scap-stats.txt" 2>"$OUT/falco-scap.stderr" &
SCAP_PID=$!
ACTIVE_PIDS+=("$SCAP_PID")
sleep 3
sample_process "$SCAP_PID" "$OUT/falco-scap-process-sample.txt"
stop_process "$SCAP_PID"

{
    echo "captured_at_utc=$STAMP"
    echo "kernel=$(uname -r)"
    echo "arch=$(uname -m)"
    echo "tetragon_version=1.7.1"
    echo "tracee_version=0.24.1"
    echo "falco_libs_version=0.26.0"
    echo "btf=$(test -r /sys/kernel/btf/vmlinux && echo yes || echo no)"
    echo "tracee_bytes=$(stat -c %s "$OUT/tracee-events.jsonl" 2>/dev/null || echo 0)"
    echo "tetragon_bytes=$(stat -c %s "$OUT/tetragon-events.jsonl" 2>/dev/null || echo 0)"
    echo "falco_bytes=$(stat -c %s "$OUT/falco-events.jsonl" 2>/dev/null || echo 0)"
} >"$OUT/run-metadata.txt"

chown -R "$CALLER_UID:$CALLER_GID" "$OUT"

echo
echo "Bake-off capture complete."
echo "$OUT"
