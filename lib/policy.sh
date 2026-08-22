#!/usr/bin/env bash

MAHO_POLICY_ROOT="${MAHO_ROOT:-$HOME/Projects/Maho-OS}"
MAHO_POLICY_AUTHORITY="$MAHO_POLICY_ROOT/lib/authority.sh"
MAHO_POLICY_INTENT="$MAHO_POLICY_ROOT/lib/intent.sh"
MAHO_POLICY_DECISION="$MAHO_POLICY_ROOT/lib/decision.sh"

if ! { [ -r "$MAHO_POLICY_AUTHORITY" ] && source "$MAHO_POLICY_AUTHORITY" 2>/dev/null; }; then
    maho_owner_get() { printf '%s\n' user; }
fi
if ! { [ -r "$MAHO_POLICY_INTENT" ] && source "$MAHO_POLICY_INTENT" 2>/dev/null; }; then
    maho_intent_get() { printf '%s\n' null; }
    maho_intent_bool() { return 1; }
fi
if ! { [ -r "$MAHO_POLICY_DECISION" ] && source "$MAHO_POLICY_DECISION" 2>/dev/null; }; then
    echo "maho-policy: decision layer unavailable" >&2
    return 1 2>/dev/null || exit 1
fi

maho_policy_wallpaper_theme() {
    local state_json="${1:-}"

    [ -n "$state_json" ] || {
        echo "maho-policy: wallpaper state JSON is required" >&2
        return 1
    }

    local normalized
    normalized="$(
        python - "$state_json" <<'PY'
import json
import os
import sys

try:
    s = json.loads(sys.argv[1])
except Exception as exc:
    raise SystemExit(f"invalid wallpaper state JSON: {exc}")

if s.get("version") != 1:
    raise SystemExit("unsupported wallpaper state version")
if s.get("kind") not in {"image", "video"}:
    raise SystemExit("unsupported wallpaper kind")
if not isinstance(s.get("provider"), str) or not s["provider"]:
    raise SystemExit("wallpaper provider is required")
if not isinstance(s.get("path"), str) or not s["path"]:
    raise SystemExit("wallpaper path is required")

path = os.path.realpath(s["path"])
if not os.path.isfile(path):
    raise SystemExit("wallpaper path is unavailable")

print(json.dumps({
    "provider": s["provider"],
    "kind": s["kind"],
    "path": path,
}, sort_keys=True))
PY
    )" || return 1

    local owner enabled mode evidence desired
    owner="$(maho_owner_get appearance.hyprland.borders 2>/dev/null || printf '%s\n' user)"

    if maho_intent_bool appearance.wallpaper.dynamic_theme false 2>/dev/null; then
        enabled=true
    else
        enabled=false
    fi

    mode="$(maho_intent_get appearance.theme.mode 2>/dev/null || printf '%s\n' '"dark"')"
    mode="$(
        printf '%s\n' "$mode" | python -c '
import json, sys
try:
    value = json.load(sys.stdin)
except Exception:
    value = "dark"
print(value if value in {"dark", "light"} else "dark")
'
    )"

    evidence="$(
        python - "$normalized" "$owner" "$enabled" <<'PY'
import json
import sys

s = json.loads(sys.argv[1])
print(json.dumps({
    "provider": s["provider"],
    "kind": s["kind"],
    "path": s["path"],
    "owner": sys.argv[2],
    "dynamic_theme": sys.argv[3] == "true",
}, sort_keys=True))
PY
    )" || return 1

    if [ "$enabled" != true ]; then
        maho_decision_create \
            appearance \
            wallpaper-theme \
            do-nothing \
            appearance.hyprland.borders \
            "Automatic wallpaper theming is disabled by user intent" \
            "$evidence" \
            '{}'
        return
    fi

    if [ "$owner" != maho ]; then
        maho_decision_create \
            appearance \
            wallpaper-theme \
            do-nothing \
            appearance.hyprland.borders \
            "Maho does not own the Hyprland border resource" \
            "$evidence" \
            '{}'
        return
    fi

    desired="$(
        python - "$normalized" "$mode" <<'PY'
import json
import sys
s=json.loads(sys.argv[1])
print(json.dumps({
    "operation": "apply-wallpaper-theme",
    "kind": s["kind"],
    "path": s["path"],
    "mode": sys.argv[2],
}, sort_keys=True))
PY
    )" || return 1

    maho_decision_create \
        appearance \
        wallpaper-theme \
        adapt \
        appearance.hyprland.borders \
        "Wallpaper changed and automatic theming is enabled for a Maho-owned resource" \
        "$evidence" \
        "$desired"
}

maho_policy_security_package_match() {
    local assessment_json="${1:-}"

    [ -n "$assessment_json" ] || {
        echo "maho-policy: security assessment JSON is required" >&2
        return 1
    }

    local normalized
    normalized="$(
        python - "$assessment_json" <<'PY'
import json
import sys

try:
    a = json.loads(sys.argv[1])
except Exception as exc:
    raise SystemExit(f"invalid security assessment JSON: {exc}")

if a.get("result") not in {"affected", "not-affected"}:
    raise SystemExit("unsupported security assessment result")
if not isinstance(a.get("package"), str) or not a["package"]:
    raise SystemExit("security assessment package is required")

print(json.dumps(a, sort_keys=True))
PY
    )" || return 1

    local evidence
    evidence="$normalized"

    local result
    result="$(printf '%s\n' "$normalized" | python -c 'import json,sys; print(json.load(sys.stdin)["result"])')"

    if [ "$result" = not-affected ]; then
        maho_decision_create \
            security \
            supply-chain-package \
            do-nothing \
            security.packages \
            "The normalized finding does not match the installed package version" \
            "$evidence" \
            '{}'
        return
    fi

    maho_decision_create \
        security \
        supply-chain-package \
        propose \
        security.packages \
        "The finding matches an installed package version; evidence should be surfaced before any response is authorized" \
        "$evidence" \
        '{"operation":"review-security-response"}'
}
