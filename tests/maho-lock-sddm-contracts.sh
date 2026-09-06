#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$ROOT/bin/maho-lock-sddm-install"
THEME="$ROOT/config/sddm/maho-lock"

fail() { printf 'FAIL  %s\n' "$*" >&2; exit 1; }
pass() { printf 'PASS  %s\n' "$*"; }

bash -n "$INSTALLER" || fail "SDDM installer syntax"
for file in Main.qml MahoSddmIcon.qml metadata.desktop theme.conf; do
    [ -r "$THEME/$file" ] || fail "missing SDDM theme source $file"
done
pass "SDDM source and installer syntax"

grep -Fq 'import SddmComponents 2.0' "$THEME/Main.qml" \
    || fail "SDDM component API import missing"
grep -Fq 'sddm.login(loginUser, passwordInput.text, sessionIndex)' "$THEME/Main.qml" \
    || fail "SDDM authentication handoff missing"
grep -Fq 'function onLoginFailed()' "$THEME/Main.qml" \
    || fail "failed authentication recovery missing"
grep -Fq 'anchors.centerIn: parent' "$THEME/Main.qml" \
    || fail "centered action content missing"
grep -Fq 'fillMode: Image.PreserveAspectCrop' "$THEME/Main.qml" \
    || fail "native wallpaper crop missing"
pass "SDDM authentication and accepted visual contracts"

sandbox="$(mktemp -d)"
trap 'rm -rf -- "$sandbox"' EXIT
export MAHO_SDDM_ALLOW_UNPRIVILEGED=1
export MAHO_SDDM_THEME_ROOT="$sandbox/themes"
export MAHO_SDDM_CONFIG_ROOT="$sandbox/config"
export MAHO_SDDM_STATE_ROOT="$sandbox/state"

bash "$INSTALLER" install >/dev/null
bash "$INSTALLER" status >/dev/null
grep -Fxq '# managed-by: maho-lock-sddm v1' "$sandbox/config/90-maho-lock.conf" \
    || fail "managed SDDM config marker missing"
grep -Fxq 'Current=maho-lock' "$sandbox/config/90-maho-lock.conf" \
    || fail "persistent SDDM theme selection missing"
[ -s "$sandbox/themes/maho-lock/assets/wallpaper" ] \
    || fail "staged wallpaper missing"
grep -Fxq 'managed-by-maho-lock-sddm-v1' \
    "$sandbox/themes/maho-lock/.managed-by-maho-lock-sddm" \
    || fail "managed theme marker missing"
pass "sandbox persistent SDDM installation"

bash "$INSTALLER" install >/dev/null
bash "$INSTALLER" status >/dev/null
pass "idempotent SDDM reinstall"

bash "$INSTALLER" uninstall >/dev/null
[ ! -e "$sandbox/config/90-maho-lock.conf" ] \
    || fail "SDDM selection survived uninstall"
[ ! -e "$sandbox/themes/maho-lock" ] \
    || fail "SDDM theme survived uninstall"
pass "recoverable managed SDDM uninstall"

printf 'PASS  Maho Lock SDDM persistence contracts\n'

