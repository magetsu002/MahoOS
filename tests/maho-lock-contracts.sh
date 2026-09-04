#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_DIR="$ROOT/config/quickshell/maho-lock"
SHELL="$LOCK_DIR/shell.qml"
SURFACE="$LOCK_DIR/MahoLockSurface.qml"
VIEW="$LOCK_DIR/MahoLockView.qml"
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

for file in "$SHELL" "$SURFACE" "$VIEW" "$PREVIEW" "$AUTH" "$STATE" "$THEME" "$PROBE" "$LAUNCHER"; do
    [ -r "$file" ] || fail "missing ${file#$ROOT/}"
done
pass "Maho Lock source files present"

bash -n "$LAUNCHER"
python3 -m py_compile "$PROBE"
pass "launcher/probe syntax"

# The production path must remain a real ext-session-lock surface. The normal
# overlay window is allowed only in preview.qml, never in the secure path.
grep -Fq 'WlSessionLock {' "$SHELL" || fail "secure ext-session-lock authority missing"
grep -Fq 'WlSessionLockSurface {' "$SURFACE" || fail "session lock surface missing"
grep -Fq 'MahoLockView {' "$SURFACE" || fail "secure surface does not render shared lock view"
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

# Wallpaper material is rendered once through MultiEffect. Rendering the raw
# image behind the effect washes the lock screen out on real hardware.
grep -Fq '/.cache/maho/theme/active.json' "$THEME" || fail "lock theme ignores active Maho palette"
grep -Fq '/maho/wallpaper/current.json' "$STATE" || fail "lock does not consume Maho wallpaper authority"
grep -Fq 'MultiEffect {' "$VIEW" || fail "target wallpaper softening is missing"
grep -Fq 'source: wallpaper' "$VIEW" || fail "blur effect is detached from wallpaper"
grep -Fq 'visible: false' "$VIEW" || fail "raw wallpaper source is still rendered under MultiEffect"
grep -Fq 'blurEnabled: true' "$VIEW" || fail "wallpaper blur disabled"
grep -Fq 'blur: 0.38' "$VIEW" || fail "wallpaper blur strength drifted from accepted restrained target"
pass "single-pass softened wallpaper material"

# Accepted target hierarchy and contrast.
grep -Fq 'Good morning' "$VIEW" || fail "time-aware greeting missing"
grep -Fq 'Screen locked' "$VIEW" || fail "top lock state missing"
grep -Fq 'Enter your password' "$VIEW" || fail "password field missing"
grep -Fq 'Press Enter to unlock' "$VIEW" || fail "keyboard affordance missing"
grep -Fq 'Sleep' "$VIEW" || fail "sleep action missing"
grep -Fq 'Switch user' "$VIEW" || fail "switch-user action missing"
grep -Fq 'Qt.rgba(1, 1, 1, 0.96)' "$VIEW" || fail "lock foreground is not contrast-stable"
if grep -Fq 'font.family: "Inter"' "$VIEW"; then
    fail "lock hardcodes an unverified font family instead of using installed system fallback"
fi
pass "accepted lock-screen visual hierarchy"

# Keyboard focus must survive the timing difference between QML construction
# and the compositor mapping/focusing the ext-session-lock surface.
grep -Fq 'FocusScope {' "$VIEW" || fail "lock view does not own a focus scope"
grep -Fq 'id: focusRecovery' "$VIEW" || fail "mapped-surface focus recovery missing"
grep -Fq 'passwordInput.forceActiveFocus()' "$VIEW" || fail "password field is never actively focused"
grep -Fq 'activeFocusOnPress: true' "$VIEW" || fail "click-to-focus password behavior missing"
grep -Fq 'selectByMouse: true' "$VIEW" || fail "password field mouse input contract missing"
grep -Fq 'Keys.onPressed' "$VIEW" || fail "password keyboard handler missing"
grep -Fq 'Qt.Key_Return' "$VIEW" || fail "Enter activation missing"
pass "session-lock keyboard focus contract"

# Preview is explicitly non-secure and separate. It renders the exact shared
# view so visual/input iteration does not require trapping the user in a real
# session lock.
grep -Fq 'PanelWindow {' "$PREVIEW" || fail "non-locking preview surface missing"
grep -Fq 'MahoLockView {' "$PREVIEW" || fail "preview does not render exact shared lock view"
grep -Fq 'previewMode: true' "$PREVIEW" || fail "preview mode is not explicit"
if grep -Eq 'WlSessionLock|PamContext' "$PREVIEW"; then
    fail "preview unexpectedly acquires session-lock/PAM authority"
fi
grep -Fq -- '--preview' "$LAUNCHER" || fail "launcher does not expose safe preview mode"
grep -Fq 'PREVIEW_CONFIG=' "$LAUNCHER" || fail "launcher preview config missing"
pass "safe exact-view preview contract"

# Calm, object-level motion only.
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
