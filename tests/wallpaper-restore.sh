#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'jobs -pr | xargs -r kill 2>/dev/null || true; rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_STATE_HOME="$TMP/state"
export XDG_CACHE_HOME="$TMP/cache"
export XDG_CONFIG_HOME="$TMP/config"
export MAHO_ROOT="$ROOT"
export MAHO_WALLPAPER_SESSION_SKIP_WAIT=1
export MAHO_WALLPAPER_SESSION_NO_WATCH=1
export PATH="$TMP/bin:$PATH"
export MAHO_TEST_AWWW_STATE="$TMP/awww-state"
export MAHO_TEST_AWWW_DAEMON="$TMP/awww-daemon"
export MAHO_TEST_COMMAND_LOG="$TMP/commands.log"

mkdir -p "$HOME" "$XDG_STATE_HOME/maho/wallpaper" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$TMP/bin"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

cat > "$TMP/bin/hyprctl" <<'EOF_HYPR'
#!/usr/bin/env bash
exit 0
EOF_HYPR

cat > "$TMP/bin/pkill" <<'EOF_PKILL'
#!/usr/bin/env bash
printf 'pkill %s\n' "$*" >> "$MAHO_TEST_COMMAND_LOG"
exit 0
EOF_PKILL

cat > "$TMP/bin/awww-daemon" <<'EOF_DAEMON'
#!/usr/bin/env bash
touch "$MAHO_TEST_AWWW_DAEMON"
while :; do
    /usr/bin/sleep 1 &
    wait $!
done
EOF_DAEMON

cat > "$TMP/bin/awww" <<'EOF_AWWW'
#!/usr/bin/env bash
set -euo pipefail
cmd="${1:-}"
shift || true
case "$cmd" in
    query)
        [ -f "$MAHO_TEST_AWWW_DAEMON" ] || exit 1
        if [ -f "$MAHO_TEST_AWWW_STATE" ]; then
            path="$(cat "$MAHO_TEST_AWWW_STATE")"
            python - "$path" <<'PY'
import json, sys
print(json.dumps({"eDP-1":[{"displaying":{"image":sys.argv[1]}}]}))
PY
        else
            printf '{}\n'
        fi
        ;;
    img)
        path="${!#}"
        printf '%s\n' "$path" > "$MAHO_TEST_AWWW_STATE"
        printf 'awww img %s\n' "$*" >> "$MAHO_TEST_COMMAND_LOG"
        ;;
    clear)
        rm -f "$MAHO_TEST_AWWW_STATE"
        printf 'awww clear\n' >> "$MAHO_TEST_COMMAND_LOG"
        ;;
    *)
        exit 2
        ;;
esac
EOF_AWWW

cat > "$TMP/bin/ffmpeg" <<'EOF_FFMPEG'
#!/usr/bin/env bash
set -euo pipefail
output="${!#}"
source=""
while [ "$#" -gt 0 ]; do
    if [ "$1" = -i ]; then
        source="$2"
        break
    fi
    shift
done
[ -n "$source" ]
printf 'poster for %s\n' "$source" > "$output"
printf 'ffmpeg %s\n' "$source" >> "$MAHO_TEST_COMMAND_LOG"
EOF_FFMPEG

cat > "$TMP/bin/mpvpaper" <<'EOF_MPV'
#!/usr/bin/env bash
printf 'mpvpaper %s\n' "${!#}" >> "$MAHO_TEST_COMMAND_LOG"
while :; do
    /usr/bin/sleep 1 &
    wait $!
done
EOF_MPV

chmod +x "$TMP/bin/"*

IMAGE="$TMP/wallpaper.jpg"
VIDEO="$TMP/wallpaper.mp4"
printf 'image\n' > "$IMAGE"
printf 'video\n' > "$VIDEO"

write_state() {
    local provider="$1"
    local kind="$2"
    local path="$3"
    python - "$XDG_STATE_HOME/maho/wallpaper/current.json" "$provider" "$kind" "$path" <<'PY'
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "version": 1,
    "provider": sys.argv[2],
    "kind": sys.argv[3],
    "path": sys.argv[4],
}, sort_keys=True) + "\n")
PY
}

# shellcheck source=../lib/authority.sh
source "$ROOT/lib/authority.sh"
# shellcheck source=../lib/intent.sh
source "$ROOT/lib/intent.sh"
# shellcheck source=../lib/events.sh
source "$ROOT/lib/events.sh"

echo "=== image restore ==="
write_state awww image "$IMAGE"
bash "$ROOT/bin/maho-wallpaper-session" restore
[ "$(cat "$MAHO_TEST_AWWW_STATE")" = "$IMAGE" ] || fail "image was not restored"
grep -Fq "awww img --transition-type none $IMAGE" "$MAHO_TEST_COMMAND_LOG" || fail "image restore was not immediate"
maho_event_last appearance | python -c '
import json, sys
e=json.load(sys.stdin)
assert e["kind"] == "wallpaper.restored"
assert e["status"] == "verified"
assert e["details"]["kind"] == "image"
'
echo "PASS"

echo "=== user ownership blocks restore ==="
maho_owner_set appearance.wallpaper.runtime user >/dev/null
rm -f "$MAHO_TEST_AWWW_STATE"
: > "$MAHO_TEST_COMMAND_LOG"
bash "$ROOT/bin/maho-wallpaper-session" restore
[ ! -e "$MAHO_TEST_AWWW_STATE" ] || fail "user-owned wallpaper runtime was mutated"
! grep -q '^awww img ' "$MAHO_TEST_COMMAND_LOG" || fail "restore ran despite user ownership"
maho_event_last appearance | python -c '
import json, sys
e=json.load(sys.stdin)
assert e["kind"] == "wallpaper.restore"
assert e["status"] == "skipped"
assert e["details"]["reason"] == "ownership"
'
echo "PASS"

echo "=== restore intent blocks restore ==="
maho_owner_set appearance.wallpaper.runtime maho >/dev/null
maho_intent_set appearance.wallpaper.restore_on_login false >/dev/null
: > "$MAHO_TEST_COMMAND_LOG"
bash "$ROOT/bin/maho-wallpaper-session" restore
! grep -q '^awww img ' "$MAHO_TEST_COMMAND_LOG" || fail "restore ran despite disabled intent"
maho_event_last appearance | python -c '
import json, sys
e=json.load(sys.stdin)
assert e["kind"] == "wallpaper.restore"
assert e["status"] == "skipped"
assert e["details"]["reason"] == "intent_disabled"
'
echo "PASS"

echo "=== video restore ==="
maho_intent_unset appearance.wallpaper.restore_on_login
write_state mpvpaper video "$VIDEO"
: > "$MAHO_TEST_COMMAND_LOG"
bash "$ROOT/bin/maho-wallpaper-session" restore
grep -Fq "mpvpaper $VIDEO" "$MAHO_TEST_COMMAND_LOG" || fail "mpvpaper restore adapter did not run"
BOOTSTRAP="$XDG_STATE_HOME/maho/wallpaper/bootstrap.jpg"
[ -s "$BOOTSTRAP" ] || fail "video boot poster was not prepared"
grep -Fq "awww img --transition-type none $BOOTSTRAP" "$MAHO_TEST_COMMAND_LOG" || fail "video poster was not shown before mpvpaper"
! grep -Fq "awww clear" "$MAHO_TEST_COMMAND_LOG" || fail "video restore discarded its matching fallback poster"
poster_line="$(grep -nF "awww img --transition-type none $BOOTSTRAP" "$MAHO_TEST_COMMAND_LOG" | cut -d: -f1)"
video_line="$(grep -nF "mpvpaper $VIDEO" "$MAHO_TEST_COMMAND_LOG" | cut -d: -f1)"
[ "$poster_line" -lt "$video_line" ] || fail "mpvpaper started before its matching poster"
maho_event_last appearance | python -c '
import json, sys
e=json.load(sys.stdin)
assert e["kind"] == "wallpaper.restored"
assert e["status"] == "verified"
assert e["details"]["kind"] == "video"
'
echo "PASS"

echo "=== stale video poster is regenerated ==="
printf 'changed video\n' >> "$VIDEO"
: > "$MAHO_TEST_COMMAND_LOG"
bash "$ROOT/bin/maho-wallpaper-session" prepare
grep -Fq "ffmpeg $VIDEO" "$MAHO_TEST_COMMAND_LOG" || fail "changed video reused a stale boot poster"
echo "PASS"

echo "=== daemon cannot replay its private cache ==="
grep -Fq 'ExecStart=/usr/bin/awww-daemon --no-cache' "$ROOT/systemd/user/maho-awww-daemon.service" || \
    fail "awww service can still replay an unrelated cached wallpaper"
grep -Fq 'awww-daemon --no-cache' "$ROOT/bin/maho-wallpaper-session" || \
    fail "fallback awww launch can still replay an unrelated cached wallpaper"
echo "PASS"

echo "ALL WALLPAPER RESTORE CONTRACTS PASS"
