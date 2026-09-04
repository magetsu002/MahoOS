#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_DIR="$ROOT/config/quickshell/maho-lock"
SHELL="$LOCK_DIR/shell.qml"
SURFACE="$LOCK_DIR/MahoLockSurface.qml"
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

for file in "$SHELL" "$SURFACE" "$AUTH" "$STATE" "$THEME" "$PROBE" "$LAUNCHER"; do
    [ -r "$file" ] || fail "missing ${file#$ROOT/}"
done
pass "Maho Lock source files present"

bash -n "$LAUNCHER"
python3 -m py_compile "$PROBE"
pass "launcher/probe syntax"

grep -Fq 'WlSessionLock {' "$SHELL" || fail "secure ext-session-lock authority missing"
grep -Fq 'WlSessionLockSurface {' "$SURFACE" || fail "session lock surface missing"
grep -Fq 'Component.onCompleted: locked = true' "$SHELL" || fail "locker does not engage on startup"
grep -Fq 'color: theme.background' "$SURFACE" || fail "lock surface is not opaque by default"
if grep -Eq 'PanelWindow|FloatingWindow' "$SHELL" "$SURFACE"; then
    fail "lock screen regressed to a normal overlay window"
fi
pass "secure Wayland session-lock boundary"

grep -Fq 'PamContext {' "$AUTH" || fail "PAM authentication missing"
grep -Fq 'config: "login"' "$AUTH" || fail "PAM login stack not selected"
grep -Fq 'result === PamResult.Success' "$AUTH" || fail "PAM success gate missing"
grep -Fq 'auth.lock.locked = false' "$AUTH" || fail "successful authentication does not release lock"
if grep -Fq 'locked = false' "$SURFACE"; then
    fail "UI surface can release session without authentication"
fi
grep -Fq 'interval: 240' "$AUTH" || fail "unlock transition is not given time to resolve"
pass "PAM-only unlock authority"

grep -Fq '/.cache/maho/theme/active.json' "$THEME" || fail "lock theme ignores active Maho palette"
grep -Fq '/maho/wallpaper/current.json' "$STATE" || fail "lock does not consume Maho wallpaper authority"
grep -Fq 'MultiEffect {' "$SURFACE" || fail "target wallpaper softening is missing"
grep -Fq 'blurEnabled: true' "$SURFACE" || fail "wallpaper blur disabled"
grep -Fq 'Good morning' "$SURFACE" || fail "time-aware greeting missing"
grep -Fq 'Screen locked' "$SURFACE" || fail "top lock state missing"
grep -Fq 'Enter your password' "$SURFACE" || fail "password field missing"
grep -Fq 'Press Enter to unlock' "$SURFACE" || fail "keyboard affordance missing"
grep -Fq 'Sleep' "$SURFACE" || fail "sleep action missing"
grep -Fq 'Switch user' "$SURFACE" || fail "switch-user action missing"
pass "accepted lock-screen visual hierarchy"

grep -Fq 'property real revealProgress: 0' "$SURFACE" || fail "entry animation state missing"
grep -Fq 'auth.unlocking' "$SURFACE" || fail "unlock transition is not wired through the surface"
grep -Fq 'Easing.OutCubic' "$SURFACE" || fail "calm native motion curve missing"
if grep -Eq 'Bounce|Elastic|OutBack|InBack' "$SURFACE"; then
    fail "lock animation uses playful/bouncy easing"
fi
pass "lock/unlock motion contract"

grep -Fq 'flock -n 9' "$LAUNCHER" || fail "locker process is not singleton-owned"
grep -Fq 'quickshell --no-duplicate -p "$CONFIG"' "$LAUNCHER" || fail "launcher does not start exact config"
if grep -Eq 'pkill|killall' "$LAUNCHER"; then
    fail "launcher uses broad process killing"
fi
if grep -Eq 'shell=True|os\.system|subprocess\.(run|Popen)\([^\n]*shell[[:space:]]*=' "$PROBE"; then
    fail "ambient state probe uses shell execution"
fi
pass "runtime ownership/security contract"

printf 'PASS  Maho Lock contracts\n'
