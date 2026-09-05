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
grep -Fq 'mainMod .. " + CTRL + L"' "$BINDS" || fail "canonical SUPER+CTRL+L bind missing"
if grep -Fq 'mainMod .. " + L"' "$BINDS"; then fail "old managed SUPER+L bind remains"; fi
grep -Fq '"$HOME/.local/bin/maho-lock"' "$BINDS" || fail "canonical bind does not use installed launcher"
pass "canonical managed SUPER+CTRL+L binding"

grep -Fq 'refusing to replace unmanaged command' "$INSTALLER" || fail "unmanaged command protection missing"
grep -Fq 'refusing to replace unmanaged runtime' "$INSTALLER" || fail "unmanaged runtime protection missing"
grep -Fq 'SUPER+CTRL+L already exists outside' "$INSTALLER" || fail "existing SUPER+CTRL+L protection missing"
grep -Fq 'live SUPER+CTRL+L ownership available' "$INSTALLER" || fail "preflight target ownership check missing"
grep -Fq 'Rolling back Maho Lock installation' "$INSTALLER" || fail "rollback path missing"
grep -Fq 'hyprctl configerrors' "$INSTALLER" || fail "post-reload config verification missing"
grep -Fq 'KEPT  user personalization state' "$INSTALLER" || fail "uninstall does not preserve personalization state"
grep -Fq 'python_syntax_check' "$INSTALLER" || fail "side-effect-free Python syntax authority missing"
grep -Fq 'ast.PyCF_ONLY_AST' "$INSTALLER" || fail "Python syntax check does not use parse-only compilation"
if grep -Fq 'py_compile' "$INSTALLER"; then
    fail "installer syntax validation can generate nondeterministic pyc files"
fi
if grep -Fq 'trap cleanup_stage RETURN' "$INSTALLER"; then
    fail "RETURN trap can delete staged runtime while install is still running"
fi
pass "installer ownership, rollback, and deterministic-runtime guards"

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

-- maho-lock-bind:begin
hl.bind(
    mainMod .. " + L",
    hl.dsp.exec_cmd([["$HOME/.local/bin/maho-lock"]])
)
-- maho-lock-bind:end
EOF_BINDS

cat > "$TMP/stubs/quickshell" <<'EOF_QUICKSHELL'
#!/usr/bin/env bash
exit 0
EOF_QUICKSHELL

cat > "$TMP/stubs/hyprctl" <<'EOF_HYPRCTL'
#!/usr/bin/env bash
case "${1:-}" in
    reload) exit 0 ;;
    configerrors)
        if [ "${MAHO_TEST_CONFIGERROR:-0}" -eq 1 ]; then
            printf 'test config error\n'
        fi
        exit 0
        ;;
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
grep -Fq 'mainMod .. " + CTRL + L"' "$XDG_CONFIG_HOME/hypr/maho/core/binds.lua" \
    || fail "managed bind was not migrated to SUPER+CTRL+L"
if grep -Fq 'mainMod .. " + L"' "$XDG_CONFIG_HOME/hypr/maho/core/binds.lua"; then
    fail "managed SUPER+L survived migration"
fi
grep -Fq 'RETURN", hl.dsp.exec_cmd("kitty")' "$XDG_CONFIG_HOME/hypr/maho/core/binds.lua" \
    || fail "installer damaged existing live bindings"

if find "$XDG_DATA_HOME/maho-lock/current/config/quickshell/maho-lock" \
    \( -type d -name '__pycache__' -o -type f -name '*.pyc' \) \
    -print -quit | grep -q .; then
    fail "installed runtime contains generated Python bytecode"
fi
pass "sandbox permanent install is deterministic and bytecode-free"

# Reinstallation must update in place without duplicating the managed bind.
bash "$INSTALLER" install >/tmp/maho-lock-reinstall-contract.out 2>&1 \
    || { cat /tmp/maho-lock-reinstall-contract.out >&2; fail "sandbox reinstall failed"; }

COUNT="$(grep -Fc -- '-- maho-lock-bind:begin' "$XDG_CONFIG_HOME/hypr/maho/core/binds.lua")"
[ "$COUNT" -eq 1 ] || fail "reinstall duplicated managed SUPER+CTRL+L binding"

if find "$XDG_DATA_HOME/maho-lock/current/config/quickshell/maho-lock" \
    \( -type d -name '__pycache__' -o -type f -name '*.pyc' \) \
    -print -quit | grep -q .; then
    fail "reinstall generated Python bytecode"
fi
pass "idempotent reinstall remains deterministic"

bash "$INSTALLER" status >/tmp/maho-lock-status-contract.out 2>&1 \
    || { cat /tmp/maho-lock-status-contract.out >&2; fail "installed status is not healthy"; }
pass "installed status"

# A failed live verification must restore the prior managed runtime, wrapper,
# and binding byte-for-byte.
cp -a "$XDG_DATA_HOME/maho-lock/current" "$TMP/runtime-before-failed-install"
cp -a "$HOME/.local/bin/maho-lock" "$TMP/wrapper-before-failed-install"
cp -a "$XDG_CONFIG_HOME/hypr/maho/core/binds.lua" "$TMP/binds-before-failed-install.lua"
if MAHO_TEST_CONFIGERROR=1 bash "$INSTALLER" install >"$TMP/failed-install.out" 2>&1; then
    fail "installer accepted a Hyprland config error"
fi
diff -ru "$TMP/runtime-before-failed-install" "$XDG_DATA_HOME/maho-lock/current" \
    || fail "failed install did not restore runtime"
cmp -s "$TMP/wrapper-before-failed-install" "$HOME/.local/bin/maho-lock" \
    || fail "failed install did not restore wrapper"
cmp -s "$TMP/binds-before-failed-install.lua" "$XDG_CONFIG_HOME/hypr/maho/core/binds.lua" \
    || fail "failed install did not restore bindings"
grep -Fq 'installation rolled back' "$TMP/failed-install.out" \
    || fail "failed install did not report rollback"
pass "failed live verification rolls back every managed artifact"

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

# An unmanaged owner of the exact target chord must survive a refused install.
cat >> "$XDG_CONFIG_HOME/hypr/maho/core/binds.lua" <<'EOF_COLLISION'
hl.bind(mainMod .. " + CTRL + L", hl.dsp.exec_cmd("custom-locker"))
EOF_COLLISION
cp -a "$XDG_CONFIG_HOME/hypr/maho/core/binds.lua" "$TMP/binds-before-collision.lua"
if bash "$INSTALLER" install >"$TMP/collision.out" 2>&1; then
    fail "installer replaced an unmanaged SUPER+CTRL+L binding"
fi
cmp -s "$TMP/binds-before-collision.lua" "$XDG_CONFIG_HOME/hypr/maho/core/binds.lua" \
    || fail "collision refusal changed live bindings"
[ ! -e "$HOME/.local/bin/maho-lock" ] || fail "collision rollback left a managed wrapper"
[ ! -e "$XDG_DATA_HOME/maho-lock/current" ] || fail "collision rollback left a managed runtime"
grep -Fq 'SUPER+CTRL+L already exists outside' "$TMP/collision.out" \
    || fail "collision refusal reason missing"
grep -Fq 'Maho Lock permanent installation' "$TMP/collision.out" \
    || fail "collision preflight did not run"
pass "unmanaged SUPER+CTRL+L collision is refused transactionally"

printf 'PASS  Maho Lock permanent installer contracts\n'
