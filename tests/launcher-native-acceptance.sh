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
RUNNING=0

exec 3>&1 4>&2
exec >"$LOG" 2>&1

cleanup() {
    rc=$?
    set +e
    if [ "$RUNNING" -eq 1 ] && [ -x "$WT/bin/maho-launcher" ]; then
        env XDG_CACHE_HOME="$CACHE" MAHO_ACTIVE_PALETTE="$PALETTE" MAHO_ROOT="$WT" \
            "$WT/bin/maho-launcher" close >>"$LOG" 2>&1
        [ -n "$WRAPPER_PID" ] && wait "$WRAPPER_PID" 2>/dev/null
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
    read -r existing_pid <"$RUNTIME_ROOT/wrapper.pid" || true
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

# Force the measured first open to regenerate its private acceptance cache.
rm -rf "$CACHE/maho/launcher"

open_once() {
    local label="$1" start_ns end_ns elapsed pid i rss
    start_ns="$(date +%s%N)"
    env XDG_CACHE_HOME="$CACHE" MAHO_ACTIVE_PALETTE="$PALETTE" MAHO_ROOT="$WT" \
        "$WT/bin/maho-launcher" open &
    WRAPPER_PID=$!
    RUNNING=1
    pid=""
    for ((i=0; i<400; i++)); do
        if [ -r "$RUNTIME_ROOT/rofi.pid" ]; then
            read -r pid <"$RUNTIME_ROOT/rofi.pid" || pid=""
            if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
                break
            fi
        fi
        pid=""
        sleep 0.01
    done
    [ -n "$pid" ] || { echo "FAIL: $label Rofi process did not become visible within 4s"; return 1; }
    end_ns="$(date +%s%N)"
    elapsed=$(( (end_ns - start_ns) / 1000000 ))
    rss="$(ps -o rss= -p "$pid" | tr -d ' ' || true)"
    printf '%s_ms=%s rss_kib=%s rofi_pid=%s\n' "$label" "$elapsed" "${rss:-unknown}" "$pid"
    OPEN_ELAPSED="$elapsed"
    OPEN_RSS="${rss:-0}"
    ROFI_PID="$pid"
}

printf '\n=== NATIVE FIRST OPEN ===\n'
OPEN_ELAPSED=0 OPEN_RSS=0 ROFI_PID=""
open_once first
FIRST_MS="$OPEN_ELAPSED"
FIRST_RSS="$OPEN_RSS"
sleep 0.35
printf '\n=== ACTIVE ROFI LAYER ===\n'
hyprctl layers 2>/dev/null | grep -C 6 -i rofi || true
grim "$SCREENSHOT"
echo "screenshot_saved=$SCREENSHOT"
env XDG_CACHE_HOME="$CACHE" MAHO_ACTIVE_PALETTE="$PALETTE" MAHO_ROOT="$WT" \
    "$WT/bin/maho-launcher" close
wait "$WRAPPER_PID" || true
RUNNING=0
WRAPPER_PID=""

printf '\n=== FIVE WARM OPENS ===\n'
declare -a TIMES=()
sum=0
for run in 1 2 3 4 5; do
    OPEN_ELAPSED=0 OPEN_RSS=0 ROFI_PID=""
    open_once "warm_$run"
    TIMES+=("$OPEN_ELAPSED")
    sum=$((sum + OPEN_ELAPSED))
    env XDG_CACHE_HOME="$CACHE" MAHO_ACTIVE_PALETTE="$PALETTE" MAHO_ROOT="$WT" \
        "$WT/bin/maho-launcher" close
    wait "$WRAPPER_PID" || true
    RUNNING=0
    WRAPPER_PID=""
    sleep 0.05
done
MEAN="$(awk -v s="$sum" 'BEGIN { printf "%.1f", s / 5 }')"
printf 'first_ms=%s first_rss_kib=%s warm_ms=%s warm_mean_ms=%s\n' \
    "$FIRST_MS" "$FIRST_RSS" "${TIMES[*]}" "$MEAN"

printf '\n=== FINAL LIFECYCLE ===\n'
env XDG_CACHE_HOME="$CACHE" MAHO_ACTIVE_PALETTE="$PALETTE" MAHO_ROOT="$WT" \
    "$WT/bin/maho-launcher" status
if [ -r "$RUNTIME_ROOT/rofi.pid" ]; then
    read -r final_rofi <"$RUNTIME_ROOT/rofi.pid" || true
    if [[ "${final_rofi:-}" =~ ^[0-9]+$ ]] && kill -0 "$final_rofi" 2>/dev/null; then
        echo "FAIL: owned Rofi process remains after close: $final_rofi"
        exit 1
    fi
fi

echo "PASS: bounded native acceptance completed; visual judgment is still pending the screenshot comparison"
