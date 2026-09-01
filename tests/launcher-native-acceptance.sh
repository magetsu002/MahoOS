#!/usr/bin/env bash
set -u

COMMIT="${1:-}"
if [[ ! "$COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
    echo "usage: launcher-native-acceptance.sh <40-char-commit-sha>" >&2
    exit 2
fi
SHORT="${COMMIT:0:8}"
ROOT_TMP="$(mktemp -d "${TMPDIR:-/tmp}/maho-launcher-accept.XXXXXX")"
WT="$ROOT_TMP/worktree"
CACHE="$ROOT_TMP/cache"
LOG="$ROOT_TMP/acceptance.log"
PALETTE="${XDG_CACHE_HOME:-$HOME/.cache}/maho/theme/active.json"
SCREENSHOT="$HOME/Pictures/maho-launcher-$SHORT.png"
RUNTIME_ROOT="${XDG_RUNTIME_DIR:-/tmp}/maho-launcher-${UID}"
REPO=""
WRAPPER_PID=""
ACTIVE_ROFI_PID=""
RUNNING=0

exec 3>&1 4>&2
exec >"$LOG" 2>&1

pid_cmdline() {
    local pid="$1"
    [ -r "/proc/$pid/cmdline" ] || return 1
    tr '\0' ' ' < "/proc/$pid/cmdline"
}

pid_is_owned_rofi() {
    local pid="$1" cmdline
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    cmdline="$(pid_cmdline "$pid" 2>/dev/null || true)"
    case "$cmdline" in
        *rofi*"$WT/config/rofi/maho-launcher/commands.sh"*"$CACHE/maho/launcher/runtime-theme.rasi"*) return 0 ;;
        *) return 1 ;;
    esac
}

owned_rofi_pid() {
    local pid child children

    if [ -r "$RUNTIME_ROOT/rofi.pid" ]; then
        read -r pid < "$RUNTIME_ROOT/rofi.pid" || pid=""
        if pid_is_owned_rofi "$pid"; then
            printf '%s\n' "$pid"
            return 0
        fi
    fi

    if [[ "$WRAPPER_PID" =~ ^[0-9]+$ ]] && [ -r "/proc/$WRAPPER_PID/task/$WRAPPER_PID/children" ]; then
        children="$(cat "/proc/$WRAPPER_PID/task/$WRAPPER_PID/children" 2>/dev/null || true)"
        for child in $children; do
            if pid_is_owned_rofi "$child"; then
                printf '%s\n' "$child"
                return 0
            fi
        done
    fi

    if command -v pgrep >/dev/null 2>&1 && [[ "$WRAPPER_PID" =~ ^[0-9]+$ ]]; then
        while IFS= read -r child; do
            if pid_is_owned_rofi "$child"; then
                printf '%s\n' "$child"
                return 0
            fi
        done < <(pgrep -P "$WRAPPER_PID" rofi 2>/dev/null || true)
    fi

    return 1
}

dump_startup_diagnostics() {
    echo "--- startup diagnostics ---"
    echo "wrapper_pid=${WRAPPER_PID:-unset}"
    echo "runtime_root=$RUNTIME_ROOT"
    ls -la "$RUNTIME_ROOT" 2>/dev/null || true
    for file in wrapper.pid rofi.pid; do
        printf '%s=' "$file"
        cat "$RUNTIME_ROOT/$file" 2>/dev/null || true
        printf '\n'
    done
    if [[ "$WRAPPER_PID" =~ ^[0-9]+$ ]]; then
        printf 'wrapper_cmdline='
        pid_cmdline "$WRAPPER_PID" 2>/dev/null || true
        printf '\nwrapper_children='
        cat "/proc/$WRAPPER_PID/task/$WRAPPER_PID/children" 2>/dev/null || true
        printf '\n'
    fi
    ps -eo pid=,ppid=,stat=,comm=,args= | grep -E '[r]ofi|[m]aho-launcher' || true
    echo "launcher log:"
    tail -n 120 "$CACHE/maho/launcher/launcher.log" 2>/dev/null || true
    echo "--- end startup diagnostics ---"
}

close_owned_launcher() {
    set +e
    if [ -x "$WT/bin/maho-launcher" ]; then
        env XDG_CACHE_HOME="$CACHE" MAHO_ACTIVE_PALETTE="$PALETTE" MAHO_ROOT="$WT" \
            "$WT/bin/maho-launcher" close >>"$LOG" 2>&1
    fi
    if [[ "$WRAPPER_PID" =~ ^[0-9]+$ ]]; then
        wait "$WRAPPER_PID" 2>/dev/null
    fi
    if pid_is_owned_rofi "${ACTIVE_ROFI_PID:-}"; then
        echo "INFO: wrapper close left exact owned Rofi child alive; terminating pid=$ACTIVE_ROFI_PID" >>"$LOG"
        kill "$ACTIVE_ROFI_PID" 2>/dev/null || true
        for _ in {1..50}; do
            kill -0 "$ACTIVE_ROFI_PID" 2>/dev/null || break
            sleep 0.01
        done
        if pid_is_owned_rofi "$ACTIVE_ROFI_PID"; then
            kill -KILL "$ACTIVE_ROFI_PID" 2>/dev/null || true
        fi
    fi
    RUNNING=0
    WRAPPER_PID=""
    ACTIVE_ROFI_PID=""
    set -e
}

cleanup() {
    rc=$?
    set +e
    if [ "$RUNNING" -eq 1 ] && [ -e "$WT/.git" ]; then
        close_owned_launcher
    fi
    if [ -n "$REPO" ] && [ -e "$WT/.git" ]; then
        git -C "$REPO" worktree remove --force "$WT" >>"$LOG" 2>&1
    fi
    printf '\n=== ACCEPTANCE RESULT ===\nexit=%s\ncommit=%s\nscreenshot=%s\n' "$rc" "$COMMIT" "$SCREENSHOT" >>"$LOG"
    if command -v wl-copy >/dev/null 2>&1; then
        printf 'clipboard=wl-copy complete diagnostic\n' >>"$LOG"
    else
        printf 'clipboard=FAILED (wl-copy unavailable)\n' >>"$LOG"
    fi

    exec 1>&3 2>&4
    if command -v wl-copy >/dev/null 2>&1; then
        wl-copy <"$LOG" || true
    fi
    cat "$LOG"
    rm -rf "$ROOT_TMP"
    trap - EXIT
    exit "$rc"
}
trap cleanup EXIT

set -Eeuo pipefail

is_maho_repo() {
    local d="$1" url
    [ -n "$d" ] && [ -e "$d/.git" ] || return 1
    url="$(git -C "$d" remote get-url origin 2>/dev/null || true)"
    case "$url" in
        *magetsu002/MahoOS* ) REPO="$d"; return 0 ;;
        * ) return 1 ;;
    esac
}

candidate="$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null || true)"
is_maho_repo "$candidate" || true
if [ -z "$REPO" ]; then
    for candidate in \
        "$HOME/Projects/MahoOS" \
        "$HOME/Projects/Maho-OS" \
        "$HOME/Projects/Maho-OS-visual-core"
    do
        is_maho_repo "$candidate" && break
    done
fi
if [ -z "$REPO" ] && [ -d "$HOME/Projects" ]; then
    while IFS= read -r marker; do
        candidate="${marker%/.git}"
        if is_maho_repo "$candidate"; then
            break
        fi
    done < <(find "$HOME/Projects" -maxdepth 3 -name .git -print 2>/dev/null)
fi
[ -n "$REPO" ] || { echo "FAIL: could not locate a clone of magetsu002/MahoOS"; exit 1; }

echo "=== EXACT REVISION ==="
echo "repo=$REPO"
git -C "$REPO" fetch --quiet origin feat/maho-launcher-rofi
FETCHED="$(git -C "$REPO" rev-parse FETCH_HEAD)"
echo "expected=$COMMIT"
echo "remote_head=$FETCHED"
[ "$FETCHED" = "$COMMIT" ] || { echo "FAIL: remote launcher branch moved; refusing to test a stale expected commit"; exit 1; }
git -C "$REPO" cat-file -e "$COMMIT^{commit}"
git -C "$REPO" worktree add --detach "$WT" "$COMMIT"
[ "$(git -C "$WT" rev-parse HEAD)" = "$COMMIT" ]
[ -z "$(git -C "$WT" status --porcelain)" ]

if [ -r "$RUNTIME_ROOT/wrapper.pid" ]; then
    read -r existing_pid < "$RUNTIME_ROOT/wrapper.pid" || true
    if [[ "${existing_pid:-}" =~ ^[0-9]+$ ]] && kill -0 "$existing_pid" 2>/dev/null; then
        echo "FAIL: a Maho Launcher instance is already running (pid=$existing_pid); refusing to disturb it"
        exit 1
    fi
fi

[ -r "$PALETTE" ] || { echo "FAIL: active Palette V2 state missing at $PALETTE"; exit 1; }
command -v rofi >/dev/null 2>&1 || { echo "FAIL: rofi missing"; exit 1; }
command -v hyprctl >/dev/null 2>&1 || { echo "FAIL: hyprctl missing"; exit 1; }
command -v grim >/dev/null 2>&1 || { echo "FAIL: grim missing; native screenshot is required"; exit 1; }
mkdir -p "$(dirname "$SCREENSHOT")"

printf '\n=== RUNTIME CAPABILITIES ===\n'
rofi -version || true
hyprctl version || true
for option in \
    decoration:blur:enabled \
    decoration:blur:size \
    decoration:blur:passes \
    decoration:blur:ignore_opacity \
    decoration:blur:xray \
    decoration:blur:noise \
    decoration:blur:contrast \
    decoration:blur:brightness \
    decoration:blur:vibrancy
do
    printf '%s: ' "$option"
    hyprctl getoption "$option" 2>/dev/null | head -n 1 || true
done

printf '\n=== CONTRACTS ===\n'
(
    cd "$WT"
    bash tests/launcher-rofi-contracts.sh
)

printf '\n=== DOCTOR ===\n'
env XDG_CACHE_HOME="$CACHE" MAHO_ACTIVE_PALETTE="$PALETTE" MAHO_ROOT="$WT" \
    "$WT/bin/maho-launcher" doctor

rm -rf "$CACHE/maho/launcher"

open_once() {
    local label="$1" start_ns end_ns elapsed pid i rss
    start_ns="$(date +%s%N)"
    env XDG_CACHE_HOME="$CACHE" MAHO_ACTIVE_PALETTE="$PALETTE" MAHO_ROOT="$WT" \
        "$WT/bin/maho-launcher" open &
    WRAPPER_PID=$!
    RUNNING=1
    ACTIVE_ROFI_PID=""

    for ((i=0; i<400; i++)); do
        pid="$(owned_rofi_pid 2>/dev/null || true)"
        if [ -n "$pid" ]; then
            ACTIVE_ROFI_PID="$pid"
            break
        fi
        sleep 0.01
    done

    if [ -z "$ACTIVE_ROFI_PID" ]; then
        echo "FAIL: $label exact owned Rofi child did not become observable within 4s"
        dump_startup_diagnostics
        return 1
    fi

    end_ns="$(date +%s%N)"
    elapsed=$(( (end_ns - start_ns) / 1000000 ))
    rss="$(ps -o rss= -p "$ACTIVE_ROFI_PID" | tr -d ' ' || true)"
    printf '%s_ms=%s rss_kib=%s rofi_pid=%s detection=pidfile-or-owned-child\n' \
        "$label" "$elapsed" "${rss:-unknown}" "$ACTIVE_ROFI_PID"
    OPEN_ELAPSED="$elapsed"
    OPEN_RSS="${rss:-0}"
}

printf '\n=== NATIVE FIRST OPEN ===\n'
OPEN_ELAPSED=0 OPEN_RSS=0
open_once first
FIRST_MS="$OPEN_ELAPSED"
FIRST_RSS="$OPEN_RSS"
sleep 0.35
printf '\n=== ACTIVE ROFI LAYER ===\n'
LAYER_OUTPUT="$(hyprctl layers 2>/dev/null || true)"
printf '%s\n' "$LAYER_OUTPUT" | grep -C 6 -i rofi || true
printf '%s\n' "$LAYER_OUTPUT" | grep -qi rofi || { echo "FAIL: owned Rofi process exists but Hyprland exposes no rofi layer"; exit 1; }
grim "$SCREENSHOT"
echo "screenshot_saved=$SCREENSHOT"
close_owned_launcher

printf '\n=== FIVE WARM OPENS ===\n'
declare -a TIMES=()
sum=0
for run in 1 2 3 4 5; do
    OPEN_ELAPSED=0 OPEN_RSS=0
    open_once "warm_$run"
    TIMES+=("$OPEN_ELAPSED")
    sum=$((sum + OPEN_ELAPSED))
    close_owned_launcher
    sleep 0.05
done
MEAN="$(awk -v s="$sum" 'BEGIN { printf "%.1f", s / 5 }')"
printf 'first_ms=%s first_rss_kib=%s warm_ms=%s warm_mean_ms=%s\n' \
    "$FIRST_MS" "$FIRST_RSS" "${TIMES[*]}" "$MEAN"

printf '\n=== FINAL LIFECYCLE ===\n'
env XDG_CACHE_HOME="$CACHE" MAHO_ACTIVE_PALETTE="$PALETTE" MAHO_ROOT="$WT" \
    "$WT/bin/maho-launcher" status

if pid="$(owned_rofi_pid 2>/dev/null || true)"; [ -n "$pid" ]; then
    echo "FAIL: exact owned Rofi process remains after close: $pid"
    exit 1
fi

echo "PASS: bounded native acceptance completed; visual judgment is still pending the screenshot comparison"
