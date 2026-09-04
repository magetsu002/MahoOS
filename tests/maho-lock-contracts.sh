#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_DIR="$ROOT/config/quickshell/maho-lock"
SHELL="$LOCK_DIR/shell.qml"
SURFACE="$LOCK_DIR/MahoLockSurface.qml"
VIEW="$LOCK_DIR/MahoLockViewV3.qml"
GLASS="$LOCK_DIR/MahoGlassCapsuleV2.qml"
ICON="$LOCK_DIR/MahoIcon.qml"
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

for file in "$SHELL" "$SURFACE" "$VIEW" "$GLASS" "$ICON" "$PREVIEW" "$AUTH" "$STATE" "$THEME" "$PROBE" "$LAUNCHER"; do
    [ -r "$file" ] || fail "missing ${file#$ROOT/}"
done
pass "Maho Lock source files present"

bash -n "$LAUNCHER"
python3 -m py_compile "$PROBE"
pass "launcher/probe syntax"

# Production remains a real ext-session-lock surface. Preview is the only
# ordinary overlay and must render the same active view.
grep -Fq 'WlSessionLock {' "$SHELL" || fail "secure ext-session-lock authority missing"
grep -Fq 'WlSessionLockSurface {' "$SURFACE" || fail "session lock surface missing"
grep -Fq 'MahoLockViewV3 {' "$SURFACE" || fail "secure surface does not render current shared view"
grep -Fq 'Component.onCompleted: locked = true' "$SHELL" || fail "locker does not engage on startup"
grep -Fq 'color: theme.background' "$SURFACE" || fail "lock surface is not opaque by default"
if grep -Eq 'PanelWindow|FloatingWindow' "$SHELL" "$SURFACE"; then
    fail "secure lock path regressed to a normal overlay window"
fi
pass "secure Wayland session-lock boundary"

# Unlock authority remains PAM-only and outside the visual component.
grep -Fq 'PamContext {' "$AUTH" || fail "PAM authentication missing"
grep -Fq 'config: "login"' "$AUTH" || fail "PAM login stack not selected"
grep -Fq 'result === PamResult.Success' "$AUTH" || fail "PAM success gate missing"
grep -Fq 'auth.lock.locked = false' "$AUTH" || fail "successful authentication does not release lock"
if grep -Fq 'locked = false' "$SURFACE" "$VIEW"; then
    fail "visual lock path can release session without authentication"
fi
grep -Fq 'interval: 240' "$AUTH" || fail "unlock transition is not given time to resolve"
pass "PAM-only unlock authority"

# Capture the wallpaper into a renderable offscreen texture instead of hiding
# the Image directly or drawing raw+effected wallpaper simultaneously.
grep -Fq '/.cache/maho/theme/active.json' "$THEME" || fail "lock theme ignores active Maho palette"
grep -Fq '/maho/wallpaper/current.json' "$STATE" || fail "lock does not consume Maho wallpaper authority"
grep -Fq 'ShaderEffectSource {' "$VIEW" || fail "offscreen wallpaper capture missing"
grep -Fq 'hideSource: true' "$VIEW" || fail "raw wallpaper is not hidden by capture authority"
grep -Fq 'source: wallpaperTexture' "$VIEW" || fail "MultiEffect is not fed from captured wallpaper texture"
grep -Fq 'blurEnabled: true' "$VIEW" || fail "wallpaper blur disabled"
grep -Fq 'blur: 0.31' "$VIEW" || fail "wallpaper blur drifted from restrained target"
grep -Fq 'brightness: 0.005' "$VIEW" || fail "wallpaper atmosphere regressed toward crushed black"
pass "single-pass wallpaper atmosphere"

# Glass is translucent material, not a painted glossy gradient or fake shadow.
grep -Fq 'MahoGlassCapsuleV2 {' "$VIEW" || fail "current glass material is not used"
[ "$(grep -Fc 'MahoGlassCapsuleV2 {' "$VIEW")" -ge 2 ] || fail "input and action do not share the same material"
grep -Fq 'fillAlpha:' "$GLASS" || fail "glass translucency authority missing"
grep -Fq 'materialTint:' "$GLASS" || fail "glass no longer receives restrained palette tint"
if grep -Eq 'GradientStop|DropShadow|Glow|OuterGlow' "$GLASS"; then
    fail "glass material regressed to painted gloss or fake glow"
fi
pass "restrained translucent glass material"

# All visible glyphs use one coherent vector-like Canvas component. Reject the
# placeholder Unicode symbols that looked optically misaligned in native proof.
grep -Fq 'Canvas {' "$ICON" || fail "professional icon component missing"
for name in lock eye power users wifi keyboard battery; do
    grep -Fq "root.icon === \"$name\"" "$ICON" || fail "missing $name glyph"
done
if grep -Eq '⏻|◎' "$VIEW"; then
    fail "placeholder text glyphs returned to lock view"
fi
grep -Fq 'MahoIcon {' "$VIEW" || fail "lock view is not using shared glyph language"
pass "coherent icon language"

# Never stringify an uninitialized UPower value as undefined%.
grep -Fq 'batteryPercentageValid' "$STATE" || fail "battery validity guard missing"
grep -Fq 'Number.isFinite' "$STATE" || fail "battery percentage is not finite-checked"
grep -Fq 'visible: state.batteryPercentageValid' "$VIEW" || fail "invalid battery readout can still render"
pass "battery readout validity guard"

# Accepted target hierarchy and contrast.
grep -Fq 'Good morning' "$VIEW" || fail "time-aware greeting missing"
grep -Fq 'Screen locked' "$VIEW" || fail "top lock state missing"
grep -Fq 'Enter your password' "$VIEW" || fail "password field missing"
grep -Fq 'Press Enter to unlock' "$VIEW" || fail "keyboard affordance missing"
grep -Fq 'Sleep' "$VIEW" || fail "sleep action missing"
grep -Fq 'Switch user' "$VIEW" || fail "switch-user action missing"
grep -Fq 'Qt.rgba(1, 1, 1, 0.965)' "$VIEW" || fail "lock foreground is not contrast-stable"
if grep -Fq 'font.family: "Inter"' "$VIEW"; then
    fail "lock hardcodes an unverified font family"
fi
pass "accepted lock-screen hierarchy"

# Keyboard focus must survive mapping timing on the real session lock.
grep -Fq 'FocusScope {' "$VIEW" || fail "lock view does not own a focus scope"
grep -Fq 'id: focusRecovery' "$VIEW" || fail "mapped-surface focus recovery missing"
grep -Fq 'passwordInput.forceActiveFocus()' "$VIEW" || fail "password field is never actively focused"
grep -Fq 'activeFocusOnPress: true' "$VIEW" || fail "click-to-focus password behavior missing"
grep -Fq 'selectByMouse: true' "$VIEW" || fail "password field mouse input contract missing"
grep -Fq 'Keys.onPressed' "$VIEW" || fail "password keyboard handler missing"
grep -Fq 'Qt.Key_Return' "$VIEW" || fail "Enter activation missing"
pass "session-lock keyboard focus contract"

# Preview stays non-secure and renders the exact production view above desktop
# chrome, allowing fidelity work without trapping the session.
grep -Fq 'PanelWindow {' "$PREVIEW" || fail "non-locking preview surface missing"
grep -Fq 'MahoLockViewV3 {' "$PREVIEW" || fail "preview does not render current production view"
grep -Fq 'previewMode: true' "$PREVIEW" || fail "preview mode is not explicit"
grep -Fq 'WlrLayershell.layer: WlrLayer.Overlay' "$PREVIEW" || fail "preview is not raised above desktop chrome"
if grep -Eq 'WlSessionLock|PamContext' "$PREVIEW"; then
    fail "preview unexpectedly acquires session-lock/PAM authority"
fi
grep -Fq -- '--preview' "$LAUNCHER" || fail "launcher does not expose safe preview mode"
grep -Fq 'PREVIEW_CONFIG=' "$LAUNCHER" || fail "launcher preview config missing"
pass "safe exact-view preview contract"

# Calm object-level motion only.
grep -Fq 'property real revealProgress: 0' "$VIEW" || fail "entry animation state missing"
grep -Fq 'auth.unlocking' "$VIEW" || fail "unlock transition is not wired through the view"
grep -Fq 'Easing.OutCubic' "$VIEW" || fail "calm native motion curve missing"
if grep -Eq 'Bounce|Elastic|OutBack|InBack' "$VIEW"; then
    fail "lock animation uses playful/bouncy easing"
fi
pass "lock/unlock motion contract"

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
