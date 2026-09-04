#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$ROOT/bin/maho-lock-install"
BINDS="$ROOT/config/hypr/maho/core/binds.lua"

fail() {
    printf 'FAIL  %s\n' "$*" >&2
    exit 1
}

pass() {
    printf 'PASS  %s\n' "$*"
}

[ -x "$INSTALLER" ] || fail "permanent installer missing or not executable"
bash -n "$INSTALLER"
pass "installer syntax"

grep -Fq -- '-- maho-lock-bind:begin' "$BINDS" || fail "canonical bind begin marker missing"
grep -Fq -- '-- maho-lock-bind:end' "$BINDS" || fail "canonical bind end marker missing"
grep -Fq 'mainMod .. " + L"' "$BINDS" || fail "canonical SUPER+L bind missing"
grep -Fq '"$HOME/.local/bin/maho-lock"' "$BINDS" || fail "canonical bind does not use installed launcher"
pass "canonical managed SUPER+L binding"

grep -Fq 'refusing to replace unmanaged command' "$INSTALLER" || fail "unmanaged command protection missing"
grep -Fq 'refusing to replace unmanaged runtime' "$INSTALLER" || fail "unmanaged runtime protection missing"
grep -Fq 'SUPER+L already exists outside' "$INSTALLER" || fail "existing SUPER+L protection missing"
grep -Fq 'Rolling back Maho Lock installation' "$INSTALLER" || fail "rollback path missing"
grep -Fq 'hyprctl configerrors' "$INSTALLER" || fail "post-reload config verification missing"
grep -Fq 'KEPT  user personalization state' "$INSTALLER" || fail "uninstall does not preserve personalization state"
if grep -Fq 'trap cleanup_stage RETURN' "$INSTALLER"; then
    fail "RETURN trap can delete staged runtime while install is still running"
fi
pass "installer ownership and rollback guards"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_STATE_HOME="$HOME/.local/state"

mkdir -p \
    "$HOME/.local/bin" \
    "$XDG_CONFIG_HOME/hypr/maho/core" \
    "$TMP/stubs"

cat > "$XDG_CONFIG_HOME/hypr/maho/core/binds.lua" <<'EOF_BINDS'
-- Maho OS stable muscle-memory bindings.
local mainMod = "SUPER"
hl.bind(mainMod .. " + RETURN", hl.dsp.exec_cmd("kitty"))
EOF_BINDS

cat > "$TMP/stubs/quickshell" <<'EOF_QUICKSHELL'
#!/usr/bin/env bash
exit 0
EOF_QUICKSHELL

cat > "$TMP/stubs/hyprctl" <<'EOF_HYPRCTL'
#!/usr/bin/env bash
case "${1:-}" in
    reload) exit 0 ;;
    configerrors) exit 0 ;;
    *) exit 0 ;;
esac
EOF_HYPRCTL

chmod +x "$TMP/stubs/quickshell" "$TMP/stubs/hyprctl"
export PATH="$TMP/stubs:$PATH"

bash "$INSTALLER" install >/tmp/maho-lock-install-contract.out 2>&1 \
    || { cat /tmp/maho-lock-install-contract.out >&2; fail "sandbox install failed"; }

[ -x "$HOME/.local/bin/maho-lock" ] || fail "installed launcher missing"
[ -f "$XDG_DATA_HOME/maho-lock/current/.managed-by-maho-lock-install" ] \
    || fail "managed runtime marker missing"
grep -Fq '# managed-by: maho-lock-install v1' "$HOME/.local/bin/maho-lock" \
    || fail "installed launcher ownership marker missing"
grep -Fq -- '-- maho-lock-bind:begin' "$XDG_CONFIG_HOME/hypr/maho/core/binds.lua" \
    || fail "live managed bind not installed"
grep -Fq 'RETURN", hl.dsp.exec_cmd("kitty")' "$XDG_CONFIG_HOME/hypr/maho/core/binds.lua" \
    || fail "installer damaged existing live bindings"
pass "sandbox permanent install"

# Reinstallation must update in place without duplicating the managed bind.
bash "$INSTALLER" install >/tmp/maho-lock-reinstall-contract.out 2>&1 \
    || { cat /tmp/maho-lock-reinstall-contract.out >&2; fail "sandbox reinstall failed"; }

COUNT="$(grep -Fc -- '-- maho-lock-bind:begin' "$XDG_CONFIG_HOME/hypr/maho/core/binds.lua")"
[ "$COUNT" -eq 1 ] || fail "reinstall duplicated managed SUPER+L binding"
pass "idempotent reinstall"

bash "$INSTALLER" status >/tmp/maho-lock-status-contract.out 2>&1 \
    || { cat /tmp/maho-lock-status-contract.out >&2; fail "installed status is not healthy"; }
pass "installed status"

bash "$INSTALLER" uninstall >/tmp/maho-lock-uninstall-contract.out 2>&1 \
    || { cat /tmp/maho-lock-uninstall-contract.out >&2; fail "sandbox uninstall failed"; }

[ ! -e "$HOME/.local/bin/maho-lock" ] || fail "managed launcher survived uninstall"
[ ! -e "$XDG_DATA_HOME/maho-lock/current" ] || fail "managed runtime survived uninstall"
if grep -Fq -- '-- maho-lock-bind:begin' "$XDG_CONFIG_HOME/hypr/maho/core/binds.lua"; then
    fail "managed SUPER+L bind survived uninstall"
fi
grep -Fq 'RETURN", hl.dsp.exec_cmd("kitty")' "$XDG_CONFIG_HOME/hypr/maho/core/binds.lua" \
    || fail "uninstall damaged pre-existing live binding"
pass "sandbox uninstall preserves unrelated live config"

printf 'PASS  Maho Lock permanent installer contracts\n'
