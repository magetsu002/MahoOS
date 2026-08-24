#!/usr/bin/env bash

MAHO_THEMES_STATE="${XDG_STATE_HOME:-$HOME/.local/state}/maho/themes"
MAHO_THEMES_CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/maho/themes"
MAHO_WALLPAPER_STATE="${XDG_STATE_HOME:-$HOME/.local/state}/maho/wallpaper"

maho_themes_wallpaper_kind() {
    local extension="${1##*.}"
    case "${extension,,}" in
        mp4|mkv|mov|webm) printf '%s\n' video ;;
        jpg|jpeg|png|webp|gif) printf '%s\n' image ;;
        *) return 1 ;;
    esac
}

maho_themes_current_wallpaper() {
    [ -r "$ROOT/bin/maho-wallpaper" ] || return 1
    bash "$ROOT/bin/maho-wallpaper" current
}

maho_themes_state_fields() {
    python - "$1" <<'PY'
import json, os, sys
value = json.loads(sys.argv[1])
provider = value.get("provider")
kind = value.get("kind")
path = value.get("path")
if provider not in {"awww", "mpvpaper"}:
    raise SystemExit("unsupported wallpaper provider: " + repr(provider))
if kind not in {"image", "video"} or not isinstance(path, str):
    raise SystemExit("invalid wallpaper state")
path = os.path.realpath(path)
if not os.path.isfile(path):
    raise SystemExit("wallpaper state points to a missing file")
print(provider)
print(kind)
print(path)
PY
}

maho_themes_verify_wallpaper() {
    local expected_kind="$1" expected_path="$2" state
    state="$(maho_themes_current_wallpaper)" || return 1
    python - "$state" "$expected_kind" "$expected_path" <<'PY'
import json, os, sys
state = json.loads(sys.argv[1])
expected_kind = sys.argv[2]
expected_path = os.path.realpath(sys.argv[3])
raise SystemExit(0 if
    state.get("kind") == expected_kind and
    os.path.realpath(state.get("path", "")) == expected_path
    else 1)
PY
}

maho_themes_apply_image() {
    local path="$1" transition="$2" duration="$3" fps="$4" i
    command -v awww >/dev/null 2>&1 || return 1
    awww query -j >/dev/null 2>&1 || return 1

    for i in $(seq 1 20); do
        if awww img --transition-type "$transition" \
            --transition-duration "$duration" --transition-fps "$fps" \
            "$path" >/dev/null 2>&1
        then
            pkill -x mpvpaper >/dev/null 2>&1 || true
            maho_themes_verify_wallpaper image "$path" || return 1
            return 0
        fi
        if awww img --transition-type fade \
            --transition-duration "$duration" --transition-fps "$fps" \
            "$path" >/dev/null 2>&1
        then
            pkill -x mpvpaper >/dev/null 2>&1 || true
            maho_themes_verify_wallpaper image "$path" || return 1
            return 0
        fi
        sleep 0.05
    done
    return 1
}

maho_themes_apply_video() {
    local path="$1" pid
    command -v mpvpaper >/dev/null 2>&1 || return 1
    pkill -x mpvpaper >/dev/null 2>&1 || true
    mpvpaper \
        -o 'loop --no-audio --hwdec=auto --profile=high-quality --video-sync=display-resample --interpolation --tscale=oversample --panscan=1.0 --video-unscaled=no' \
        '*' "$path" >>"$MAHO_THEMES_STATE/mpvpaper.log" 2>&1 &
    pid=$!
    sleep 0.35
    kill -0 "$pid" 2>/dev/null || return 1
    maho_themes_verify_wallpaper video "$path"
}

maho_themes_apply_runtime() {
    local kind="$1" path="$2" transition="$3" duration="$4" fps="$5"
    case "$kind" in
        image) maho_themes_apply_image "$path" "$transition" "$duration" "$fps" ;;
        video) maho_themes_apply_video "$path" ;;
        *) return 1 ;;
    esac
}

maho_themes_video_frame() {
    local path="$1" output="$2" duration seek
    command -v ffmpeg >/dev/null 2>&1 || return 1
    command -v ffprobe >/dev/null 2>&1 || return 1
    duration="$(ffprobe -v error -show_entries format=duration \
        -of default=noprint_wrappers=1:nokey=1 "$path" 2>/dev/null || true)"
    seek="$(python - "$duration" <<'PY'
import sys
try:
    duration = float(sys.argv[1])
except Exception:
    duration = 2.0
print(f"{duration * 0.25 if duration > 4 else 0.5:.3f}")
PY
)"
    ffmpeg -loglevel error -y -ss "$seek" -i "$path" \
        -frames:v 1 -q:v 2 "$output"
}

maho_themes_write_status() {
    local status="$1" txn="$2" detail="$3"
    mkdir -p "$MAHO_THEMES_STATE"
    python - "$status" "$txn" "$detail" <<'PY' >"$MAHO_THEMES_STATE/.last-transaction.json.$$"
import json, sys
print(json.dumps({
    "version": 1,
    "status": sys.argv[1],
    "transaction": sys.argv[2],
    "detail": sys.argv[3],
}, sort_keys=True))
PY
    mv "$MAHO_THEMES_STATE/.last-transaction.json.$$" \
        "$MAHO_THEMES_STATE/last-transaction.json"
}

maho_themes_publish_wallpaper() {
    local kind="$1" path="$2" provider
    provider=awww
    [ "$kind" = video ] && provider=mpvpaper
    mkdir -p "$MAHO_WALLPAPER_STATE" "$MAHO_THEMES_CACHE"
    python - "$provider" "$kind" "$path" <<'PY' >"$MAHO_WALLPAPER_STATE/.current.json.$$"
import json, os, sys
print(json.dumps({
    "version": 1,
    "provider": sys.argv[1],
    "kind": sys.argv[2],
    "path": os.path.realpath(sys.argv[3]),
}, sort_keys=True))
PY
    mv "$MAHO_WALLPAPER_STATE/.current.json.$$" "$MAHO_WALLPAPER_STATE/current.json"
    printf '%s|%s\n' "$kind" "$path" >"$MAHO_THEMES_CACHE/.last_wallpaper.$$"
    mv "$MAHO_THEMES_CACHE/.last_wallpaper.$$" "$MAHO_THEMES_CACHE/last_wallpaper"
}

maho_themes_publish_palette() {
    local candidate="$1" previous="$2"
    mkdir -p "$CACHE"
    if [ -f "$previous" ]; then
        cp "$previous" "$CACHE/.previous.json.$$" || return 1
        mv "$CACHE/.previous.json.$$" "$CACHE/previous.json" || return 1
    fi
    cp "$candidate" "$CACHE/.active.json.$$" || return 1
    mv "$CACHE/.active.json.$$" "$CACHE/active.json"
}

maho_themes_restore_palette() {
    local previous="$1"
    [ -f "$previous" ] || return 1
    hypr_apply_palette_file "$previous" 0 >/dev/null || return 1
    cp "$previous" "$CACHE/.active.json.$$" || return 1
    mv "$CACHE/.active.json.$$" "$CACHE/active.json"
}

maho_themes_restore_wallpaper() {
    local state="$1"
    local -a fields
    mapfile -t fields < <(maho_themes_state_fields "$state") || return 1
    maho_themes_apply_runtime "${fields[1]}" "${fields[2]}" fade 0.4 60
}

maho_themes_rollback() {
    local before_wallpaper="$1" previous_palette="$2"
    local wallpaper_ok=0 palette_ok=0
    local -a fields
    if maho_themes_restore_wallpaper "$before_wallpaper" &&
       mapfile -t fields < <(maho_themes_state_fields "$before_wallpaper") &&
       maho_themes_publish_wallpaper "${fields[1]}" "${fields[2]}"
    then
        wallpaper_ok=1
    fi
    maho_themes_restore_palette "$previous_palette" && palette_ok=1
    [ "$wallpaper_ok" -eq 1 ] && [ "$palette_ok" -eq 1 ]
}

maho_themes_validate_active_palette() {
    python - "$1" <<'PY'
import json, re, sys
try:
    value = json.load(open(sys.argv[1]))
except Exception as exc:
    raise SystemExit(f"invalid active palette: {exc}")
if value.get("version") != 1 or not isinstance(value.get("colors"), dict):
    raise SystemExit("invalid active palette envelope")
for name in ("foreground", "primary"):
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value["colors"].get(name, "")):
        raise SystemExit("invalid active palette color: " + name)
PY
}

maho_themes_validate_apply_options() {
    local transition="$1" duration="$2" fps="$3"
    case "$transition" in
        fade|wipe|wave|grow|center|outer|any) ;;
        *) return 1 ;;
    esac
    [[ "$duration" =~ ^[0-9]+([.][0-9]+)?$ ]] || return 1
    [[ "$fps" =~ ^[0-9]+$ ]] || return 1
    python - "$duration" "$fps" <<'PY'
import sys
duration = float(sys.argv[1])
fps = int(sys.argv[2])
raise SystemExit(0 if 0 <= duration <= 10 and 1 <= fps <= 240 else 1)
PY
}

maho_themes_apply_transaction() {
    local wallpaper="${1:-}" mode="${2:-dark}"
    if [ "$#" -ge 2 ]; then
        shift 2
    elif [ "$#" -ge 1 ]; then
        shift
    fi
    local transition=fade duration=0.6 fps=60

    while [ "$#" -gt 0 ]; do
        case "$1" in
            --transition) transition="${2:-}"; shift 2 ;;
            --duration) duration="${2:-}"; shift 2 ;;
            --fps) fps="${2:-}"; shift 2 ;;
            *) die "unknown apply option: $1"; return 1 ;;
        esac
    done

    [ -f "$wallpaper" ] || { die "wallpaper does not exist: $wallpaper"; return 1; }
    case "$mode" in dark|light) ;; *) die "mode must be dark or light"; return 1 ;; esac
    maho_themes_validate_apply_options "$transition" "$duration" "$fps" || {
        die "invalid wallpaper transition settings"
        return 1
    }

    local wall kind txn palette_source before_wallpaper candidate previous_palette
    wall="$(realpath "$wallpaper")" || return 1
    kind="$(maho_themes_wallpaper_kind "$wall")" || {
        die "unsupported wallpaper format"
        return 1
    }
    txn="$CACHE/transactions/themes-$(date +%Y%m%d-%H%M%S)-$$"
    mkdir -p "$txn" "$MAHO_THEMES_STATE" "$MAHO_THEMES_CACHE"
    palette_source="$wall"
    if [ "$kind" = video ]; then
        palette_source="$txn/video-frame.jpg"
        maho_themes_video_frame "$wall" "$palette_source" || {
            die "could not extract a palette frame from video"
            return 1
        }
    fi

    generate "$palette_source" "$mode" || return 1
    candidate="$CACHE/candidate.json"
    cp "$candidate" "$txn/candidate.json" || return 1
    candidate="$txn/candidate.json"

    before_wallpaper="$(maho_themes_current_wallpaper)" || {
        die "cannot capture one authoritative current wallpaper; refusing mutation"
        return 1
    }
    maho_themes_state_fields "$before_wallpaper" >/dev/null || return 1
    printf '%s\n' "$before_wallpaper" >"$txn/before-wallpaper.json"

    previous_palette="$txn/previous-active.json"
    [ -f "$CACHE/active.json" ] || {
        die "no active Maho palette exists; refusing a transaction without palette rollback"
        return 1
    }
    maho_themes_validate_active_palette "$CACHE/active.json" || return 1
    cp "$CACHE/active.json" "$previous_palette" || return 1

    maho_themes_write_status applying "$txn" "candidate validated; runtime mutation pending"
    if ! maho_themes_apply_runtime "$kind" "$wall" "$transition" "$duration" "$fps"; then
        maho_themes_write_status failed "$txn" "wallpaper apply failed before palette mutation"
        die "wallpaper application failed; active palette was not changed"
        return 1
    fi

    if [ "${MAHO_THEME_TEST_FAIL_AFTER_WALLPAPER:-0}" = 1 ] ||
       ! hypr_apply_palette_file "$candidate" 0 >/dev/null
    then
        if maho_themes_rollback "$before_wallpaper" "$previous_palette"; then
            maho_themes_write_status rolled_back "$txn" "palette apply failed; previous wallpaper and palette restored"
            die "palette application failed; previous wallpaper and palette restored"
        else
            maho_themes_write_status rollback_failed "$txn" "palette apply failed and rollback could not be verified"
            die "palette application failed and rollback could not be fully verified"
        fi
        return 1
    fi

    if ! maho_themes_verify_wallpaper "$kind" "$wall"; then
        maho_themes_rollback "$before_wallpaper" "$previous_palette" || true
        maho_themes_write_status rolled_back "$txn" "wallpaper verification failed"
        die "wallpaper verification failed; rollback attempted"
        return 1
    fi

    if ! maho_themes_publish_palette "$candidate" "$previous_palette" ||
       ! cmp -s "$candidate" "$CACHE/active.json" ||
       ! maho_themes_publish_wallpaper "$kind" "$wall"
    then
        maho_themes_rollback "$before_wallpaper" "$previous_palette" || true
        maho_themes_write_status rolled_back "$txn" "commit verification failed"
        die "theme commit failed; rollback attempted"
        return 1
    fi

    maho_themes_write_status committed "$txn" "wallpaper and Palette V2 verified"
    echo "PASS"
    echo "Maho Themes transaction committed"
    sha256sum "$CACHE/active.json"
}
