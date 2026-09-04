#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_DIR="$ROOT/config/quickshell/maho-lock"
SHELL="$LOCK_DIR/shell.qml"
SURFACE="$LOCK_DIR/MahoLockSurface.qml"
VIEW="$LOCK_DIR/MahoLockViewV4.qml"
GLASS="$LOCK_DIR/MahoGlassCapsuleV3.qml"
ICON="$LOCK_DIR/MahoIconV2.qml"
ACTION="$LOCK_DIR/MahoActionButton.qml"
WALLPAPER="$LOCK_DIR/assets/maho-lock-dusk.jpg"
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
    "$SHELL" "$SURFACE" "$VIEW" "$GLASS" "$ICON" "$ACTION" \
    "$WALLPAPER" "$PREVIEW" "$AUTH" "$STATE" "$THEME" "$PROBE" "$LAUNCHER"
do
    [ -r "$file" ] || fail "missing ${file#$ROOT/}"
done
[ -s "$WALLPAPER" ] || fail "bundled lock wallpaper is empty"
pass "Maho Lock source and wallpaper assets present"

bash -n "$LAUNCHER"
python3 -m py_compile "$PROBE"
pass "launcher/probe syntax"

# Production remains a real ext-session-lock surface.
grep -Fq 'WlSessionLock {' "$SHELL" || fail "secure ext-session-lock authority missing"
grep -Fq 'WlSessionLockSurface {' "$SURFACE" || fail "session lock surface missing"
grep -Fq 'MahoLockViewV4 {' "$SURFACE" || fail "secure surface does not render current shared view"
grep -Fq 'Component.onCompleted: locked = true' "$SHELL" || fail "locker does not engage on startup"
grep -Fq 'color: theme.background' "$SURFACE" || fail "lock surface is not opaque by default"
if grep -Eq 'PanelWindow|FloatingWindow' "$SHELL" "$SURFACE"; then
    fail "secure lock path regressed to a normal overlay window"
fi
pass "secure Wayland session-lock boundary"

# Unlock authority remains PAM-only.
grep -Fq 'PamContext {' "$AUTH" || fail "PAM authentication missing"
grep -Fq 'config: "login"' "$AUTH" || fail "PAM login stack not selected"
grep -Fq 'result === PamResult.Success' "$AUTH" || fail "PAM success gate missing"
grep -Fq 'auth.lock.locked = false' "$AUTH" || fail "successful authentication does not release lock"
if grep -Fq 'locked = false' "$SURFACE" "$VIEW"; then
    fail "visual lock path can release session without authentication"
fi
pass "PAM-only unlock authority"

# V1 target now has a deterministic Maho lock wallpaper rather than depending
# on the live desktop wallpaper renderer, which repeatedly produced black proof.
grep -Fq '/maho/wallpaper/current.json' "$STATE" || fail "desktop wallpaper authority is no longer observable"
grep -Fq 'lockWallpaperUrl' "$STATE" || fail "dedicated lock wallpaper authority missing"
grep -Fq 'assets/maho-lock-dusk.jpg' "$STATE" || fail "chosen Maho dusk wallpaper not selected"
grep -Fq 'source: state.lockWallpaperUrl' "$VIEW" || fail "active lock view does not use chosen wallpaper"
if grep -Eq 'ShaderEffectSource|MultiEffect' "$VIEW"; then
    fail "pre-softened dedicated wallpaper should not pass through another fragile full-screen effect"
fi
pass "deterministic chosen lock wallpaper"

# Glass is quiet translucency, not a painted gradient or glow.
grep -Fq 'MahoGlassCapsuleV3 {' "$VIEW" || fail "current glass material is not used"
[ "$(grep -Fc 'MahoGlassCapsuleV3 {' "$VIEW")" -ge 2 ] || fail "input and action do not share material"
grep -Fq 'fillAlpha:' "$GLASS" || fail "glass translucency authority missing"
grep -Fq 'calmTint:' "$GLASS" || fail "glass no longer receives restrained palette tint"
if grep -Eq 'GradientStop|DropShadow|Glow|OuterGlow' "$GLASS"; then
    fail "glass material regressed to painted gloss or fake glow"
fi
pass "restrained translucent glass material"

# Visible icons are SVG-backed instead of Canvas/Unicode placeholder glyphs.
grep -Fq 'Image {' "$ICON" || fail "SVG-backed icon renderer missing"
grep -Fq 'icons/' "$ICON" || fail "icon renderer is not backed by icon assets"
if grep -Fq 'Canvas {' "$ICON"; then
    fail "low-quality Canvas icon renderer returned"
fi
for name in lock eye power users wifi keyboard battery; do
    [ -s "$LOCK_DIR/icons/$name.svg" ] || fail "missing SVG icon: $name"
done
if grep -Eq '⏻|◎' "$VIEW"; then
    fail "placeholder Unicode symbols returned"
fi
grep -Fq 'MahoIconV2 {' "$VIEW" || fail "lock view is not using SVG icon language"
pass "professional SVG icon language"

# Never render an uninitialized UPower percentage.
grep -Fq 'batteryPercentageValid' "$STATE" || fail "battery validity guard missing"
grep -Fq 'Number.isFinite' "$STATE" || fail "battery percentage is not finite-checked"
grep -Fq 'visible: state.batteryPercentageValid' "$VIEW" || fail "invalid battery readout can still render"
pass "battery readout validity guard"

# Target hierarchy.
grep -Fq 'Good morning' "$VIEW" || fail "time-aware greeting missing"
grep -Fq 'Screen locked' "$VIEW" || fail "top lock state missing"
grep -Fq 'Enter your password' "$VIEW" || fail "password field missing"
grep -Fq 'Press Enter to unlock' "$VIEW" || fail "keyboard affordance missing"
grep -Fq 'Sleep' "$VIEW" || fail "sleep action missing"
grep -Fq 'Switch user' "$VIEW" || fail "switch-user action missing"
if grep -Fq 'Lock preview' "$VIEW"; then
    fail "preview-only top chrome leaked into target hierarchy"
fi
pass "accepted lock-screen hierarchy"

# Focus/input behavior remains stable.
grep -Fq 'FocusScope {' "$VIEW" || fail "lock view does not own a focus scope"
grep -Fq 'id: focusRecovery' "$VIEW" || fail "mapped-surface focus recovery missing"
grep -Fq 'passwordInput.forceActiveFocus()' "$VIEW" || fail "password field is never actively focused"
grep -Fq 'activeFocusOnPress: true' "$VIEW" || fail "click-to-focus password behavior missing"
grep -Fq 'selectByMouse: true' "$VIEW" || fail "password field mouse input contract missing"
grep -Fq 'Keys.onPressed' "$VIEW" || fail "password keyboard handler missing"
grep -Fq 'Qt.Key_Return' "$VIEW" || fail "Enter activation missing"
pass "session-lock keyboard focus contract"

# Preview stays non-secure and renders the exact production view.
grep -Fq 'PanelWindow {' "$PREVIEW" || fail "non-locking preview surface missing"
grep -Fq 'MahoLockViewV4 {' "$PREVIEW" || fail "preview does not render current production view"
grep -Fq 'previewMode: true' "$PREVIEW" || fail "preview mode is not explicit"
grep -Fq 'WlrLayershell.layer: WlrLayer.Overlay' "$PREVIEW" || fail "preview is not raised above desktop chrome"
if grep -Eq 'WlSessionLock|PamContext' "$PREVIEW"; then
    fail "preview unexpectedly acquires session-lock/PAM authority"
fi
grep -Fq -- '--preview' "$LAUNCHER" || fail "launcher does not expose safe preview mode"
pass "safe exact-view preview contract"

# Motion is now visible at entry and interaction level, while keeping Maho's
# calm cubic language.
grep -Fq 'property real introProgress: 0' "$VIEW" || fail "entry animation state missing"
grep -Fq 'duration: 680' "$VIEW" || fail "lock entry animation is no longer perceptible"
grep -Fq 'errorFlash' "$VIEW" || fail "authentication error material animation missing"
grep -Fq 'pressed: unlockPointer.pressed' "$VIEW" || fail "Unlock press animation missing"
grep -Fq 'eyePointer.pressed' "$VIEW" || fail "eye control press animation missing"
grep -Fq 'MahoActionButton {' "$VIEW" || fail "animated bottom actions missing"
grep -Fq 'root.pressed ? 0.96' "$ACTION" || fail "bottom action press response missing"
grep -Fq 'interval: 150' "$VIEW" || fail "bottom action transition delay missing"
grep -Fq 'Easing.OutCubic' "$VIEW" "$GLASS" "$ACTION" || fail "native motion curve missing"
if grep -Eq 'Bounce|Elastic|OutBack|InBack' "$VIEW" "$GLASS" "$ACTION"; then
    fail "lock animation uses playful/bouncy easing"
fi
pass "visible calm interaction motion"

# Production process ownership remains singleton and narrowly scoped.
grep -Fq 'flock -n 9' "$LAUNCHER" || fail "locker process is not singleton-owned"
grep -Fq 'quickshell --no-duplicate -p "$CONFIG"' "$LAUNCHER" || fail "launcher does not start exact secure config"
if grep -Eq 'pkill|killall' "$LAUNCHER"; then
    fail "launcher uses broad process killing"
fi
if grep -Eq 'shell=True|os\.system|subprocess\.(run|Popen)\([^\n]*shell[[:space:]]*=' "$PROBE"; then
    fail "ambient state probe uses shell execution"
fi
pass "runtime ownership/security contract"

printf 'PASS  Maho Lock contracts\n'
