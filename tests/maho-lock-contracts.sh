#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_DIR="$ROOT/config/quickshell/maho-lock"
SHELL="$LOCK_DIR/shell.qml"
SURFACE="$LOCK_DIR/MahoLockSurface.qml"
BASE_VIEW="$LOCK_DIR/MahoLockViewV5.qml"
VIEW="$LOCK_DIR/MahoLockViewV6.qml"
GLASS="$LOCK_DIR/MahoGlassCapsuleV3.qml"
ICON="$LOCK_DIR/MahoIconV2.qml"
ACTION="$LOCK_DIR/MahoActionButton.qml"
PREVIEW="$LOCK_DIR/preview.qml"
AUTH="$LOCK_DIR/MahoLockAuth.qml"
STATE="$LOCK_DIR/MahoLockState.qml"
THEME="$LOCK_DIR/MahoLockTheme.qml"
PROBE="$LOCK_DIR/state.py"
LAUNCHER="$ROOT/bin/maho-lock"

fail() {
    printf 'FAIL  %s\n' "$*" >&2
    exit 1
}

pass() {
    printf 'PASS  %s\n' "$*"
}

for file in \
    "$SHELL" "$SURFACE" "$BASE_VIEW" "$VIEW" "$GLASS" "$ICON" "$ACTION" \
    "$PREVIEW" "$AUTH" "$STATE" "$THEME" "$PROBE" "$LAUNCHER"
do
    [ -r "$file" ] || fail "missing ${file#$ROOT/}"
done
pass "Maho Lock V6 source files present"

bash -n "$LAUNCHER"
python3 -m py_compile "$PROBE"
pass "launcher/probe syntax"

# Production remains a real Wayland session lock, never a fake overlay.
grep -Fq 'WlSessionLock {' "$SHELL" || fail "secure ext-session-lock authority missing"
grep -Fq 'WlSessionLockSurface {' "$SURFACE" || fail "session lock surface missing"
grep -Fq 'MahoLockViewV6 {' "$SURFACE" || fail "secure surface does not render V6"
grep -Fq 'Component.onCompleted: locked = true' "$SHELL" || fail "locker does not engage on startup"
if grep -Eq 'PanelWindow|FloatingWindow' "$SHELL" "$SURFACE"; then
    fail "secure lock path regressed to ordinary window"
fi
pass "secure Wayland lock boundary"

# PAM remains the only unlock authority.
grep -Fq 'PamContext {' "$AUTH" || fail "PAM authentication missing"
grep -Fq 'config: "login"' "$AUTH" || fail "PAM login stack missing"
grep -Fq 'result === PamResult.Success' "$AUTH" || fail "PAM success gate missing"
grep -Fq 'auth.lock.locked = false' "$AUTH" || fail "PAM success does not release lock"
if grep -Fq 'locked = false' "$SURFACE" "$BASE_VIEW" "$VIEW"; then
    fail "visual path can release session lock"
fi
pass "PAM-only unlock authority"

# Random local wallpaper authority stays user-controlled and bounded.
grep -Fq 'MAHO_LOCK_WALLPAPER_DIR' "$PROBE" || fail "wallpaper directory override missing"
grep -Fq 'MAHO_LOCK_WALLPAPER_FILE' "$PROBE" || fail "explicit wallpaper override missing"
grep -Fq 'random.SystemRandom().choice' "$PROBE" || fail "wallpaper randomization missing"
grep -Fq -- '--pick-wallpaper' "$PROBE" || fail "wallpaper picker CLI missing"
grep -Fq 'source: root.lockState.lockWallpaperUrl' "$BASE_VIEW" || fail "active view ignores lock wallpaper"
grep -Fq 'root.lockState.chooseLockWallpaper()' "$VIEW" || fail "preview personalization cannot shuffle wallpaper"
pass "random local lock wallpaper authority"

# Battery icon represents charge level and charging state, with calm charging motion.
for name in battery battery-25 battery-50 battery-75 battery-full battery-charging; do
    [ -s "$LOCK_DIR/icons/$name.svg" ] || fail "missing battery asset: $name"
done
grep -Fq 'resolvedName' "$ICON" || fail "dynamic battery icon selection missing"
grep -Fq 'batteryCharging' "$ICON" || fail "charging icon state missing"
grep -Fq 'batteryFull' "$ICON" || fail "full battery state missing"
grep -Fq 'battery-25' "$ICON" || fail "low battery icon state missing"
grep -Fq 'battery-full' "$ICON" || fail "full battery icon asset not selected"
grep -Fq 'battery-charging' "$ICON" || fail "charging asset not selected"
grep -Fq 'chargingPulse' "$ICON" || fail "charging state has no visual motion"
grep -Fq 'Easing.InOutSine' "$ICON" || fail "charging pulse is not calm"
grep -Fq 'Number.isFinite' "$STATE" || fail "battery percentage is not finite checked"
grep -Fq 'batteryStatusText' "$STATE" || fail "battery semantic status missing"
pass "semantic animated battery state"

# Top-right chrome is interactive, animated, and bounded to lock-safe actions.
grep -Fq 'statusInteractive' "$ICON" || fail "status icon interaction missing"
grep -Fq 'name === "wifi"' "$ICON" || fail "Wi-Fi status interaction missing"
grep -Fq 'name === "battery"' "$ICON" || fail "battery status interaction missing"
grep -Fq 'name === "keyboard"' "$ICON" || fail "keyboard status interaction missing"
grep -Fq 'statusBubble' "$ICON" || fail "status feedback bubble missing"
grep -Fq 'iconVisual' "$ICON" || fail "status hover/press animation missing"
grep -Fq 'Manage in Maho Link after unlock' "$ICON" || fail "Wi-Fi interaction lacks safe routing"
grep -Fq -- '--switch-layout' "$ICON" || fail "keyboard icon does not use bounded layout switch helper"
grep -Fq 'Active layout' "$ICON" || fail "keyboard interaction lacks state feedback"
if grep -Eq 'nmcli.*(radio|connection).*down|rfkill|ip link.*down' "$ICON"; then
    fail "lock screen can destructively change network state"
fi
pass "animated lock-safe status chrome"

# Password visibility has explicit eye-open and eye-slashed states.
[ -s "$LOCK_DIR/icons/eye.svg" ] || fail "eye-open asset missing"
[ -s "$LOCK_DIR/icons/eye-off.svg" ] || fail "eye-off asset missing"
grep -Fq 'name: "eye"' "$BASE_VIEW" || fail "eye-open state missing"
grep -Fq 'name: "eye-off"' "$BASE_VIEW" || fail "eye-slashed state missing"
grep -Fq 'root.passwordVisible' "$BASE_VIEW" || fail "eye state is not visibility-driven"
pass "password visibility glyph states"

# Profile-photo editing is available only in non-locking preview mode and its
# panel actually animates both open and closed instead of disappearing instantly.
[ -s "$LOCK_DIR/icons/edit.svg" ] || fail "profile edit icon missing"
grep -Fq 'MahoLockViewV5 {' "$VIEW" || fail "V6 no longer preserves accepted V5 hierarchy"
grep -Fq 'root.previewMode' "$VIEW" || fail "profile editor is not preview-gated"
grep -Fq 'profileProgress' "$VIEW" || fail "profile panel transition state missing"
grep -Fq 'root.profileOpen || root.profileProgress > 0.001' "$VIEW" || fail "profile panel cannot animate closed"
grep -Fq 'avatarReveal' "$VIEW" || fail "profile photo entrance motion missing"
grep -Fq 'refreshAvatarCandidates' "$VIEW" || fail "profile candidate UI missing"
grep -Fq 'setAvatar' "$VIEW" || fail "profile selection action missing"
grep -Fq 'clearAvatar' "$VIEW" || fail "initials reset action missing"
grep -Fq 'New wallpaper' "$VIEW" || fail "personalization panel lacks wallpaper action"
grep -Fq -- '--avatar-candidates' "$PROBE" || fail "avatar candidate CLI missing"
grep -Fq -- '--set-avatar' "$PROBE" || fail "avatar persistence CLI missing"
grep -Fq 'profile_state_path' "$PROBE" || fail "avatar persistence state missing"
grep -Fq 'avatarPath' "$STATE" || fail "lock state does not expose avatar"
pass "animated preview-only personalization editor"

# Preview remains safe and renders the production view.
grep -Fq 'PanelWindow {' "$PREVIEW" || fail "safe preview window missing"
grep -Fq 'MahoLockViewV6 {' "$PREVIEW" || fail "preview does not render V6"
grep -Fq 'previewMode: true' "$PREVIEW" || fail "preview mode not explicit"
grep -Fq 'WlrLayershell.layer: WlrLayer.Overlay' "$PREVIEW" || fail "preview is not above desktop chrome"
if grep -Eq 'WlSessionLock|PamContext' "$PREVIEW"; then
    fail "preview unexpectedly acquires session lock or PAM"
fi
pass "safe exact-view preview"

# Accepted hierarchy and motion remain intact in V5 base.
grep -Fq 'Good morning' "$BASE_VIEW" || fail "time-aware greeting missing"
grep -Fq 'Screen locked' "$BASE_VIEW" || fail "lock state label missing"
grep -Fq 'Enter your password' "$BASE_VIEW" || fail "password field missing"
grep -Fq 'Press Enter to unlock' "$BASE_VIEW" || fail "keyboard affordance missing"
grep -Fq 'Sleep' "$BASE_VIEW" || fail "sleep action missing"
grep -Fq 'Switch user' "$BASE_VIEW" || fail "switch-user action missing"
grep -Fq 'property real introProgress: 0' "$BASE_VIEW" || fail "entry motion state missing"
grep -Fq 'duration: 700' "$BASE_VIEW" || fail "entry motion duration drifted"
grep -Fq 'Easing.OutCubic' "$BASE_VIEW" "$VIEW" "$ICON" || fail "native cubic motion missing"
if grep -Eq 'Bounce|Elastic|OutBack|InBack' "$BASE_VIEW" "$VIEW" "$ICON"; then
    fail "playful/bouncy easing entered lock UI"
fi
pass "accepted hierarchy and calm motion"

# Process ownership remains singleton and narrowly scoped.
grep -Fq 'flock -n 9' "$LAUNCHER" || fail "locker process is not singleton owned"
grep -Fq 'quickshell --no-duplicate -p "$CONFIG"' "$LAUNCHER" || fail "launcher does not start exact secure config"
if grep -Eq 'pkill|killall' "$LAUNCHER"; then
    fail "launcher uses broad process killing"
fi
if grep -Eq 'shell=True|os\.system|subprocess\.(run|Popen)\([^\n]*shell[[:space:]]*=' "$PROBE"; then
    fail "state probe uses shell execution"
fi
pass "runtime ownership/security contract"

printf 'PASS  Maho Lock preinstall contracts\n'
