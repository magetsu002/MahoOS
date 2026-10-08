#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_CONFIG_HOME="$TMP/config"
export XDG_DATA_HOME="$TMP/data"
export XDG_STATE_HOME="$TMP/state"
export XDG_CACHE_HOME="$TMP/cache"
mkdir -p "$HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_STATE_HOME" "$XDG_CACHE_HOME"

fail() { echo "FAIL: $*" >&2; exit 1; }

# Load setup functions in a completely isolated user environment. The script's
# default help output is intentionally suppressed; no install action is invoked.
set -- __contract_load__
source "$REPO_ROOT/bin/maho-setup" >/dev/null
mkdir -p "$(dirname -- "$HYPR_TARGET")"

cat >"$HYPR_TARGET" <<'EOF_LIVE_HYPR'
-- Own graphical Maho services only while this Hyprland session is alive.

hl.on("hyprland.start", function()
    hl.exec_cmd([["$HOME/.local/bin/maho-session" start]])
end)

hl.on("hyprland.shutdown", function()
    hl.exec_cmd([["$HOME/.local/bin/maho-session" stop]])
end)
EOF_LIVE_HYPR

EXPECTED_SHA='e792a37a0f8189302ef21a60afc52744eb86c5bae312525ac414540b911e2d15'
ACTUAL_SHA="$(sha256sum "$HYPR_TARGET" | awk '{print $1}')"
[ "$ACTUAL_SHA" = "$EXPECTED_SHA" ] || fail "fixture drifted from recovered live hook: $ACTUAL_SHA"

before="$(sha256sum "$HYPR_TARGET" | awk '{print $1}')"
validate_targets >/dev/null || fail 'exact recovered markerless Hyprland hook was rejected'
after="$(sha256sum "$HYPR_TARGET" | awk '{print $1}')"
[ "$before" = "$after" ] || fail 'validation mutated the recovered live hook'
echo 'PASS exact recovered markerless Hyprland hook is recognized without mutation'

printf '%s\n' '-- unrelated external mutation' >>"$HYPR_TARGET"
mutated_before="$(sha256sum "$HYPR_TARGET" | awk '{print $1}')"
if validate_targets >"$TMP/reject.out" 2>"$TMP/reject.err"; then
  fail 'near-match Hyprland hook was incorrectly accepted'
fi
mutated_after="$(sha256sum "$HYPR_TARGET" | awk '{print $1}')"
[ "$mutated_before" = "$mutated_after" ] || fail 'failed validation mutated the unrelated hook'
grep -Fq 'refusing unmanaged Maho Hyprland config' "$TMP/reject.err" || fail 'rejection did not identify Hyprland ownership conflict'
echo 'PASS near-match Hyprland hook remains fail-closed and non-mutating'

cat >"$HYPR_TARGET" <<'EOF_OLDER_HYPR'
-- Own graphical Maho services only while this Hyprland session is alive.

hl.on("hyprland.start", function()
    hl.exec_cmd([["$HOME/.local/bin/maho-session" start]])
    hl.exec_cmd("waybar")
end)

hl.on("hyprland.shutdown", function()
    hl.exec_cmd([["$HOME/.local/bin/maho-session" stop]])
end)
EOF_OLDER_HYPR
validate_targets >/dev/null || fail 'older exact Maho + Waybar migration hook regressed'
echo 'PASS older exact Maho + Waybar migration hook remains recognized'

echo '=== exact Settings component loader migration ownership ==='
settings_component="$XDG_DATA_HOME/maho/components/maho-settings/current"
settings_hypr_target="$(hypr_target_for config/hypr/hyprland.lua)"
mkdir -p "$settings_component"
cat >"$settings_component/loader.lua" <<'EOF_SETTINGS_LOADER'
-- Maho Settings component loader.
-- Immutable Maho defaults stay owned by runtime/current. This loader adds only
-- the Settings window/key surface plus the bounded maho.user.settings overlay.
local home = os.getenv("HOME")
assert(home ~= nil and home ~= "", "HOME is unavailable")
dofile(home .. "/.local/share/maho/runtime/current/config/hypr/hyprland.lua")

hl.window_rule({
    name = "maho-settings-component",
    match = { class = "^(io\\.maho\\.Settings)$" },
    float = true,
    center = true,
    size = { "monitor_w * 0.75", "monitor_h * 0.84" },
    border_size = 0,
    rounding = 20,
})

hl.unbind("SUPER + CTRL + SHIFT + S")
hl.bind(
    "SUPER + CTRL + SHIFT + S",
    hl.dsp.exec_cmd([["$HOME/.local/bin/maho-settings" toggle]])
)

local user_settings = package.searchpath("maho.user.settings", package.path)
if user_settings ~= nil then
    require("maho.user.settings")
end
EOF_SETTINGS_LOADER
ln -sfn "$settings_component/loader.lua" "$settings_hypr_target"
validate_targets >/dev/null || fail 'exact Settings component loader was rejected'
printf '\n-- unrelated mutation\n' >>"$settings_component/loader.lua"
if validate_targets >"$TMP/settings-reject.out" 2>"$TMP/settings-reject.err"; then
  fail 'mutated Settings component loader was incorrectly accepted'
fi
grep -Fq 'refusing unmanaged Maho Hyprland config' "$TMP/settings-reject.err" || fail 'Settings loader rejection did not identify Hyprland ownership conflict'
echo 'PASS exact Settings loader migration is accepted and later mutation fails closed'

rm -f "$settings_hypr_target"

echo '=== exact live kbdlight migration ownership ==='
mkdir -p "$HOME/.local/bin" "$UNIT_DIR"
cp "$REPO_ROOT/bin/maho-kbdlight" "$HOME/.local/bin/maho-kbdlight"
chmod +x "$HOME/.local/bin/maho-kbdlight"
cp "$REPO_ROOT/systemd/user/maho-kbdlight.service" "$UNIT_DIR/maho-kbdlight.service"
validate_targets >/dev/null || fail 'exact live kbdlight helper/unit were rejected'
printf '\n# unauthorized mutation\n' >> "$HOME/.local/bin/maho-kbdlight"
if validate_targets >"$TMP/kbd-reject.out" 2>"$TMP/kbd-reject.err"; then
  fail 'mutated kbdlight helper was incorrectly accepted'
fi
grep -Fq 'refusing unmanaged command' "$TMP/kbd-reject.err" || fail 'kbdlight rejection did not identify command ownership conflict'
echo 'PASS exact kbdlight migration is accepted and later mutation fails closed'

echo 'ALL LIVE MIGRATION OWNERSHIP CONTRACTS PASS'
