#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BINDS="$ROOT/config/hypr/maho/core/binds.lua"
INPUT="$ROOT/config/hypr/maho/core/input.lua"
SETUP="$ROOT/bin/maho-setup"
fail() { echo "FAIL: $*" >&2; exit 1; }
require() { grep -Fq -- "$2" "$1" || fail "$3"; }

echo '=== canonical accepted Hyprland behavior ==='
require "$BINDS" 'mainMod .. " + CTRL + RETURN"' 'launcher shortcut is not canonical'
require "$BINDS" 'screenshot-select-copy' 'region screenshot shortcut is not canonical'
require "$BINDS" 'screenshot-copy' 'full screenshot shortcut is not canonical'
require "$BINDS" 'active.class == "brave-browser"' 'Brave fullscreen compatibility is not canonical'
require "$BINDS" 'hl.dsp.window.fullscreen_state({' 'Brave fullscreen compatibility lost supported state dispatch'
require "$BINDS" 'XF86AudioMicMute' 'microphone mute key regressed'
require "$BINDS" 'mainMod .. " + SHIFT + W"' 'Wi-Fi Link shortcut is not canonical'
require "$BINDS" 'mainMod .. " + SHIFT + B"' 'Bluetooth Link shortcut is not canonical'
require "$INPUT" 'disable_while_typing = false' 'accepted touchpad typing behavior is not canonical input state'
echo PASS

echo '=== bounded Acer keyboard-light quirk ==='
require "$BINDS" 'readFirstLine("/sys/class/dmi/id/sys_vendor") == "Acer"' 'Acer quirk is not vendor bounded'
require "$BINDS" 'readFirstLine("/sys/class/dmi/id/product_name") == "Predator PHN16-72"' 'Acer quirk is not exact-model bounded'
require "$BINDS" 'hasKeyboardLightHelper' 'Acer quirk does not require the machine-local helper'
require "$BINDS" 'if acerKeyboardLightQuirk then' 'Acer touchpad-key remap is unconditional'
echo PASS

echo '=== immutable Hyprland authority ==='
for rel in \
  config/hypr/hyprland.lua \
  config/hypr/maho/core/windowing.lua \
  config/hypr/maho/core/input.lua \
  config/hypr/maho/core/binds.lua \
  config/hypr/maho/core/session.lua \
  config/hypr/maho/appearance/decorations.lua \
  config/hypr/maho/appearance/animations.lua \
  config/hypr/maho/theme/fallback.lua \
  config/hypr/maho/theme/palette.lua; do
  require "$SETUP" "$rel" "setup does not own $rel through runtime/current"
done
require "$SETUP" 'managed_hypr_file' 'setup status cannot verify individual Hyprland runtime authority'
require "$SETUP" 'safe_hypr_file' 'setup migration does not protect unrelated Hyprland state'
require "$SETUP" 'legacy_hypr_managed_file' 'setup cannot migrate the exact reviewed live Hyprland baseline'
require "$SETUP" 'cmp -s "$path" "$(runtime_path "$rel")"' 'setup cannot safely adopt an exact current-runtime regular file'
echo PASS

echo 'ALL MANAGED HYPRLAND CONFIG CONTRACTS PASS'
