#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_DIR="$ROOT/config/quickshell/maho-lock"
SHELL="$LOCK_DIR/shell.qml"
SURFACE="$LOCK_DIR/MahoLockSurface.qml"
VIEW="$LOCK_DIR/MahoLockViewV5.qml"
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
    "$SHELL" "$SURFACE" "$VIEW" "$GLASS" "$ICON" "$ACTION" \
    "$PREVIEW" "$AUTH" "$STATE" "$THEME" "$PROBE" "$LAUNCHER"
do
    [ -r "$file" ] || fail "missing ${file#$ROOT/}"
done
pass "Maho Lock V5 source files present"

bash -n "$LAUNCHER"
python3 -m py_compile "$PROBE"
pass "launcher/probe syntax"

# Production stays behind the real Wayland session-lock authority.
grep -Fq 'WlSessionLock {' "$SHELL" || fail "secure ext-session-lock authority missing"
grep -Fq 'WlSessionLockSurface {' "$SURFACE" || fail "session lock surface missing"
grep -Fq 'MahoLockViewV5 {' "$SURFACE" || fail "secure surface does not render V5"
grep -Fq 'lockState: root.state' "$SURFACE" || fail "secure surface does not bind explicit lock state"
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

# User wallpaper selection is one-shot and restricted to wallpaper-oriented
# roots/current wallpaper unless the user explicitly overrides the directory.
grep -Fq -- '--pick-wallpaper' "$PROBE" || fail "random wallpaper picker command missing"
grep -Fq 'MAHO_LOCK_WALLPAPER_DIR' "$PROBE" || fail "wallpaper directory override missing"
grep -Fq 'MAHO_LOCK_WALLPAPER_FILE' "$PROBE" || fail "wallpaper file override missing"
grep -Fq 'SystemRandom' "$PROBE" || fail "wallpaper picker is not randomized"
grep -Fq 'selectedLockWallpaperPath' "$STATE" || fail "one-shot selected wallpaper state missing"
grep -Fq 'id: wallpaperPicker' "$STATE" || fail "wallpaper picker process missing"
grep -Fq 'state.chooseLockWallpaper()' "$STATE" || fail "wallpaper selection is not started once"
grep -Fq 'source: root.lockState.lockWallpaperUrl' "$VIEW" || fail "V5 does not consume selected wallpaper"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/home/Pictures/Wallpapers" "$TMP/runtime"
printf 'a' > "$TMP/home/Pictures/Wallpapers/a.jpg"
printf 'b' > "$TMP/home/Pictures/Wallpapers/b.png"
PICKED="$({
    HOME="$TMP/home" \
    XDG_RUNTIME_DIR="$TMP/runtime" \
    python3 "$PROBE" --pick-wallpaper
} | python3 -c 'import json,sys; print(json.load(sys.stdin)["path"])')"
case "$PICKED" in
    "$TMP/home/Pictures/Wallpapers/a.jpg"|"$TMP/home/Pictures/Wallpapers/b.png") ;;
    *) fail "wallpaper picker escaped the wallpaper collection: $PICKED" ;;
esac
pass "random local wallpaper authority"

# Arbitrary local images are softened once behind the translucent material.
grep -Fq 'ShaderEffectSource {' "$VIEW" || fail "wallpaper capture missing"
grep -Fq 'hideSource: true' "$VIEW" || fail "raw wallpaper is not hidden by capture authority"
grep -Fq 'MultiEffect {' "$VIEW" || fail "wallpaper softening effect missing"
grep -Fq 'blur: 0.34' "$VIEW" || fail "wallpaper blur drifted from V5 target"
grep -Fq 'brightness: 0.018' "$VIEW" || fail "wallpaper brightness drifted from V5 target"
pass "single-pass wallpaper atmosphere"

# Glass remains restrained and shared by input/action.
grep -Fq 'MahoGlassCapsuleV3 {' "$VIEW" || fail "current glass material is not used"
[ "$(grep -Fc 'MahoGlassCapsuleV3 {' "$VIEW")" -ge 2 ] || fail "input and action do not share material"
grep -Fq 'fillAlpha:' "$GLASS" || fail "glass translucency authority missing"
grep -Fq 'calmTint:' "$GLASS" || fail "glass no longer receives restrained palette tint"
if grep -Eq 'DropShadow|Glow|OuterGlow' "$GLASS"; then
    fail "glass material regressed to fake glow"
fi
pass "restrained translucent glass material"

# SVG icon language and explicit open/slashed-eye state.
grep -Fq 'Image {' "$ICON" || fail "SVG-backed icon renderer missing"
if grep -Fq 'Canvas {' "$ICON"; then
    fail "low-quality Canvas icon renderer returned"
fi
for name in lock eye eye-off power users wifi keyboard battery; do
    [ -s "$LOCK_DIR/icons/$name.svg" ] || fail "missing SVG icon: $name"
done
grep -Fq 'name: "eye"' "$VIEW" || fail "open-eye state missing"
grep -Fq 'name: "eye-off"' "$VIEW" || fail "slashed-eye state missing"
grep -Fq 'root.passwordVisible' "$VIEW" || fail "eye state is not bound to password visibility"
pass "professional password visibility icon states"

# Explicit root.lockState qualification prevents QML Item.state shadowing, which
# previously produced a black wallpaper, blank monogram and undefined%.
if grep -Eq '(^|[^.[:alnum:]_])state\.(displayName|lockWallpaperUrl|networkKind|battery|keyboardLayout|switchUserCommand)' "$VIEW"; then
    fail "unqualified state access can be shadowed by QML Item.state"
fi
grep -Fq 'root.lockState.displayName' "$VIEW" || fail "display name is not explicitly qualified"
grep -Fq 'root.lockState.batteryPercentageValid' "$VIEW" || fail "battery validity is not explicitly qualified"
grep -Fq 'root.lockState.keyboardLayout' "$VIEW" || fail "keyboard layout is not explicitly qualified"
grep -Fq 'Number.isFinite' "$STATE" || fail "battery percentage is not finite-checked"
grep -Fq '? root.lockState.batteryPercentage + "%"' "$VIEW" || fail "battery text does not guard invalid values"
pass "state-shadowing and undefined readout regression guard"

# Target composition is deliberately closer to the accepted mockup.
grep -Fq 'Good morning' "$VIEW" || fail "time-aware greeting missing"
grep -Fq 'Screen locked' "$VIEW" || fail "top lock state missing"
grep -Fq 'Enter your password' "$VIEW" || fail "password field missing"
grep -Fq 'Press Enter to unlock' "$VIEW" || fail "keyboard affordance missing"
grep -Fq 'width: 112 * root.uiScale' "$VIEW" || fail "target avatar scale drifted"
grep -Fq 'anchors.topMargin: 456 * root.uiScale' "$VIEW" || fail "target auth vertical rhythm drifted"
grep -Fq 'width: 444 * root.uiScale' "$VIEW" || fail "target input width drifted"
grep -Fq 'Sleep' "$VIEW" || fail "sleep action missing"
grep -Fq 'Switch user' "$VIEW" || fail "switch-user action missing"
pass "target-aligned lock hierarchy"

# Focus/input behavior remains stable.
grep -Fq 'FocusScope {' "$VIEW" || fail "lock view does not own a focus scope"
grep -Fq 'id: focusRecovery' "$VIEW" || fail "mapped-surface focus recovery missing"
grep -Fq 'passwordInput.forceActiveFocus()' "$VIEW" || fail "password field is never actively focused"
grep -Fq 'activeFocusOnPress: true' "$VIEW" || fail "click-to-focus password behavior missing"
grep -Fq 'selectByMouse: true' "$VIEW" || fail "password field mouse input contract missing"
grep -Fq 'Keys.onPressed' "$VIEW" || fail "password keyboard handler missing"
grep -Fq 'Qt.Key_Return' "$VIEW" || fail "Enter activation missing"
pass "session-lock keyboard focus contract"

# Preview stays non-secure and uses the exact production V5 view.
grep -Fq 'PanelWindow {' "$PREVIEW" || fail "non-locking preview surface missing"
grep -Fq 'MahoLockViewV5 {' "$PREVIEW" || fail "preview does not render V5"
grep -Fq 'lockState: state' "$PREVIEW" || fail "preview does not bind explicit lock state"
grep -Fq 'previewMode: true' "$PREVIEW" || fail "preview mode is not explicit"
grep -Fq 'WlrLayershell.layer: WlrLayer.Overlay' "$PREVIEW" || fail "preview is not above desktop chrome"
if grep -Eq 'WlSessionLock|PamContext' "$PREVIEW"; then
    fail "preview unexpectedly acquires session-lock/PAM authority"
fi
pass "safe exact-view preview contract"

# Visible calm animation remains part of the component rather than compositor
# magic or playful bounce easing.
grep -Fq 'property real introProgress: 0' "$VIEW" || fail "entry animation state missing"
grep -Fq 'duration: 700' "$VIEW" || fail "V5 entry animation duration drifted"
grep -Fq 'errorFlash' "$VIEW" || fail "authentication error animation missing"
grep -Fq 'eyePointer.pressed' "$VIEW" || fail "eye interaction animation missing"
grep -Fq 'MahoActionButton {' "$VIEW" || fail "animated bottom actions missing"
grep -Fq 'Easing.OutCubic' "$VIEW" "$GLASS" "$ACTION" || fail "native motion curve missing"
if grep -Eq 'Bounce|Elastic|OutBack|InBack' "$VIEW" "$GLASS" "$ACTION"; then
    fail "lock animation uses playful/bouncy easing"
fi
pass "visible calm lock motion"

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
