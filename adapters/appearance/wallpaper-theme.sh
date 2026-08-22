#!/usr/bin/env bash

set -u

ROOT="${MAHO_ROOT:-$HOME/Projects/Maho-OS}"
THEME="$ROOT/bin/maho-theme"
THEME_CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/maho/theme"
WALL_CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/maho/wallpaper"
LOG="${XDG_STATE_HOME:-$HOME/.local/state}/maho/wallpaper/watch.log"

mkdir -p "$THEME_CACHE" "$WALL_CACHE" "$(dirname -- "$LOG")"

die() {
    echo "wallpaper-theme-adapter: $*" >&2
    return 1
}

normalize_desired() {
    local raw="${1:-}"
    python - "$raw" <<'PY'
import json
import os
import sys

try:
    d=json.loads(sys.argv[1])
except Exception as exc:
    raise SystemExit(f"invalid desired state: {exc}")

if not isinstance(d, dict):
    raise SystemExit("desired state must be an object")
if d.get("operation") != "apply-wallpaper-theme":
    raise SystemExit("unsupported operation")
kind=d.get("kind")
if kind not in {"image","video"}:
    raise SystemExit("kind must be image or video")
path=d.get("path")
if not isinstance(path,str) or not path:
    raise SystemExit("path is required")
path=os.path.realpath(path)
if not os.path.isfile(path):
    raise SystemExit("wallpaper path does not exist")
mode=d.get("mode","dark")
if mode not in {"dark","light"}:
    raise SystemExit("mode must be dark or light")
print(json.dumps({
    "operation":"apply-wallpaper-theme",
    "kind":kind,
    "path":path,
    "mode":mode,
}, sort_keys=True))
PY
}

maho_hyprctl() {
    command -v hyprctl >/dev/null 2>&1 || return 1

    if [ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]; then
        hyprctl "$@"
        return
    fi

    local instance
    instance="$(
        hyprctl instances -j 2>/dev/null |
        python -c '
import json,sys
try:
    rows=json.load(sys.stdin)
except Exception:
    raise SystemExit(1)
if len(rows) != 1:
    raise SystemExit(2)
value=rows[0].get("instance")
if not isinstance(value,str) or not value:
    raise SystemExit(1)
print(value)
'
    )" || return $?

    hyprctl -i "$instance" "$@"
}

read_gradient() {
    local option="$1"
    maho_hyprctl getoption "$option" -j |
        python -c 'import json,sys; print(json.load(sys.stdin)["gradient"])'
}

gradient_to_rgba() {
    python - "$1" <<'PY'
import re,sys
value=sys.argv[1].strip()
m=re.fullmatch(r"([0-9a-fA-F]{8}) 0deg", value)
if not m:
    raise SystemExit("unsupported border gradient: "+repr(value))
argb=m.group(1).lower()
print("rgba("+argb[2:]+argb[:2]+")")
PY
}

set_borders() {
    local active="$1"
    local inactive="$2"
    local out
    out="$(
        maho_hyprctl eval \
            "hl.config({ general = { col = { active_border = \"$active\", inactive_border = \"$inactive\" }}})" \
            2>&1
    )" || return 1
    [ "$out" = "ok" ]
}

cache_snapshot() {
    python - "$THEME_CACHE" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
out={}
for name in ("active","previous","candidate"):
    p=root/f"{name}.json"
    if not p.is_file():
        out[name]=None
        continue
    try:
        value=json.loads(p.read_text())
    except Exception as exc:
        raise SystemExit(f"invalid existing theme cache {p}: {exc}")
    if not isinstance(value,dict):
        raise SystemExit(f"invalid existing theme cache object: {p}")
    out[name]=value
print(json.dumps(out, sort_keys=True))
PY
}

capture() {
    local active inactive active_rgba inactive_rgba cache

    active="$(read_gradient general:col.active_border)" || return 1
    inactive="$(read_gradient general:col.inactive_border)" || return 1

    # Refuse mutation when exact rollback cannot be represented safely.
    active_rgba="$(gradient_to_rgba "$active")" || return 1
    inactive_rgba="$(gradient_to_rgba "$inactive")" || return 1
    cache="$(cache_snapshot)" || return 1

    python - "$active" "$inactive" "$active_rgba" "$inactive_rgba" "$cache" <<'PY'
import json,sys
active,inactive,active_rgba,inactive_rgba,cache_raw=sys.argv[1:]
print(json.dumps({
    "active_gradient":active,
    "inactive_gradient":inactive,
    "active_rgba":active_rgba,
    "inactive_rgba":inactive_rgba,
    "cache":json.loads(cache_raw),
}, sort_keys=True))
PY
}

video_source() {
    local path="$1"
    command -v ffmpeg >/dev/null 2>&1 || return 1
    command -v ffprobe >/dev/null 2>&1 || return 1

    local duration seek frame tmp
    duration="$(
        ffprobe -v error -show_entries format=duration \
            -of default=noprint_wrappers=1:nokey=1 "$path" 2>/dev/null || true
    )"
    seek="$(
        python - "$duration" <<'PY'
import sys
try:
    value=float(sys.argv[1])
except Exception:
    value=2.0
print(f"{value*0.25 if value>4 else 0.5:.3f}")
PY
    )"

    frame="$WALL_CACHE/video-frame.jpg"
    tmp="$WALL_CACHE/.video-frame.$$.jpg"
    if ! ffmpeg -loglevel error -y -ss "$seek" -i "$path" -frames:v 1 -q:v 2 "$tmp"; then
        rm -f "$tmp"
        return 1
    fi
    mv "$tmp" "$frame"
    printf '%s\n' "$frame"
}

apply_desired() {
    local desired="$1"
    local normalized kind path mode source
    normalized="$(normalize_desired "$desired")" || return 1

    mapfile -t fields < <(
        python - "$normalized" <<'PY'
import json,sys
d=json.loads(sys.argv[1])
print(d["kind"])
print(d["path"])
print(d["mode"])
PY
    )
    kind="${fields[0]}"
    path="${fields[1]}"
    mode="${fields[2]}"
    source="$path"

    [ -r "$THEME" ] || return 1

    if [ "$kind" = video ]; then
        source="$(video_source "$path")" || return 1
    fi

    bash "$THEME" apply "$source" "$mode" >> "$LOG" 2>&1
}

verify_desired() {
    local desired="$1"
    local normalized kind path mode active inactive errors
    normalized="$(normalize_desired "$desired")" || return 1

    mapfile -t fields < <(
        python - "$normalized" "$THEME_CACHE/active.json" "$WALL_CACHE/video-frame.jpg" <<'PY'
import json,os,re,sys
wanted=json.loads(sys.argv[1])
active_path=sys.argv[2]
video_frame=os.path.realpath(sys.argv[3])
try:
    active=json.loads(open(active_path).read())
except Exception:
    raise SystemExit(1)
if active.get("version") != 1 or active.get("mode") != wanted["mode"]:
    raise SystemExit(1)
colors=active.get("colors",{})
for key in ("foreground","primary"):
    if not isinstance(colors.get(key),str) or not re.fullmatch(r"#[0-9a-fA-F]{6}",colors[key]):
        raise SystemExit(1)
source=os.path.realpath(active.get("source",{}).get("path", ""))
if wanted["kind"] == "image":
    if source != wanted["path"]:
        raise SystemExit(1)
else:
    if source != video_frame or not os.path.isfile(video_frame):
        raise SystemExit(1)
print("ff"+colors["foreground"][1:].lower()+" 0deg")
print("ff"+colors["primary"][1:].lower()+" 0deg")
PY
    ) || return 1

    active="$(read_gradient general:col.active_border)" || return 1
    inactive="$(read_gradient general:col.inactive_border)" || return 1

    [ "${active,,}" = "${fields[0],,}" ] || return 1
    [ "${inactive,,}" = "${fields[1],,}" ] || return 1

    errors="$(maho_hyprctl configerrors 2>&1)" || return 1
    [ -z "$errors" ]
}

restore_cache() {
    local before="$1"
    python - "$before" "$THEME_CACHE" <<'PY'
import json,os,sys
from pathlib import Path
before=json.loads(sys.argv[1])
cache=before.get("cache")
if not isinstance(cache,dict):
    raise SystemExit(1)
root=Path(sys.argv[2])
root.mkdir(parents=True, exist_ok=True)
for name in ("active","previous","candidate"):
    value=cache.get(name)
    path=root/f"{name}.json"
    if value is None:
        path.unlink(missing_ok=True)
        continue
    if not isinstance(value,dict):
        raise SystemExit(1)
    tmp=root/f".{name}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True)+"\n")
    os.replace(tmp,path)
PY
}

rollback() {
    local before="$1"
    local active inactive
    mapfile -t fields < <(
        python - "$before" <<'PY'
import json,sys
b=json.loads(sys.argv[1])
for key in ("active_rgba","inactive_rgba"):
    value=b.get(key)
    if not isinstance(value,str) or not value:
        raise SystemExit(1)
    print(value)
PY
    ) || return 1
    active="${fields[0]}"
    inactive="${fields[1]}"

    set_borders "$active" "$inactive" || return 1
    restore_cache "$before"
}

verify_rollback() {
    local before="$1"
    local active inactive
    active="$(read_gradient general:col.active_border)" || return 1
    inactive="$(read_gradient general:col.inactive_border)" || return 1

    python - "$before" "$active" "$inactive" "$THEME_CACHE" <<'PY'
import json,sys
from pathlib import Path
before=json.loads(sys.argv[1])
if sys.argv[2].lower() != str(before.get("active_gradient","")).lower():
    raise SystemExit(1)
if sys.argv[3].lower() != str(before.get("inactive_gradient","")).lower():
    raise SystemExit(1)
cache=before.get("cache")
if not isinstance(cache,dict):
    raise SystemExit(1)
root=Path(sys.argv[4])
for name in ("active","previous","candidate"):
    expected=cache.get(name)
    path=root/f"{name}.json"
    if expected is None:
        if path.exists():
            raise SystemExit(1)
        continue
    if not path.is_file():
        raise SystemExit(1)
    try:
        actual=json.loads(path.read_text())
    except Exception:
        raise SystemExit(1)
    if actual != expected:
        raise SystemExit(1)
PY
}

case "${1:-}" in
    capture)
        normalize_desired "${2:-}" >/dev/null || exit 1
        capture
        ;;
    apply)
        apply_desired "${2:-}"
        ;;
    verify)
        verify_desired "${2:-}"
        ;;
    rollback)
        rollback "${2:-}"
        ;;
    verify-rollback)
        verify_rollback "${2:-}"
        ;;
    *)
        die "usage: wallpaper-theme.sh capture|apply|verify|rollback|verify-rollback JSON"
        exit 2
        ;;
esac
