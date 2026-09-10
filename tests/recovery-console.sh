#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_DATA_HOME="$TMP/data"
mkdir -p "$HOME/.local/bin" "$XDG_DATA_HOME/maho/runtime/releases/current" "$XDG_DATA_HOME/maho/runtime/releases/previous"

CURRENT_RELEASE="$XDG_DATA_HOME/maho/runtime/releases/current"
PREVIOUS_RELEASE="$XDG_DATA_HOME/maho/runtime/releases/previous"
cat >"$CURRENT_RELEASE/manifest.json" <<'EOF_CURRENT'
{"version":3,"source_revision":"current-revision","content_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
EOF_CURRENT
cat >"$PREVIOUS_RELEASE/manifest.json" <<'EOF_PREVIOUS'
{"version":3,"source_revision":"previous-revision","content_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}
EOF_PREVIOUS
ln -s "$CURRENT_RELEASE" "$XDG_DATA_HOME/maho/runtime/current"
ln -s "$PREVIOUS_RELEASE" "$XDG_DATA_HOME/maho/runtime/previous"

SETUP_LOG="$TMP/setup.log"
export SETUP_LOG
cat >"$TMP/fake-setup" <<'EOF_SETUP'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$SETUP_LOG"
[ "$*" = rollback ] || exit 88
EOF_SETUP
chmod +x "$TMP/fake-setup"

PLATFORM_LOG="$TMP/platform.log"
export PLATFORM_LOG
cat >"$TMP/fake-platform" <<'EOF_PLATFORM'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$PLATFORM_LOG"
case "$1" in
  status) printf 'platform status fixture\n' ;;
  doctor) printf 'platform doctor fixture\n' ;;
  plan) printf '{"action":"diagnose-only"}\n' ;;
  *) exit 89 ;;
esac
EOF_PLATFORM
chmod +x "$TMP/fake-platform"

export MAHO_ROOT="$ROOT"
export MAHO_SETUP_COMMAND="$TMP/fake-setup"
export MAHO_PLATFORM_COMMAND="$TMP/fake-platform"

inspect="$(bash "$ROOT/bin/maho-recovery" inspect)"
grep -Fq "$CURRENT_RELEASE" <<<"$inspect"
grep -Fq 'current-revision' <<<"$inspect"
grep -Fq "$PREVIOUS_RELEASE" <<<"$inspect"
grep -Fq 'previous-revision' <<<"$inspect"
grep -Fq 'platform status fixture' <<<"$inspect"
[ ! -s "$SETUP_LOG" ] || { echo 'FAIL inspect invoked a mutating setup action' >&2; exit 1; }
echo 'PASS recovery inspection is read-only and shows both immutable runtimes'

set +e
printf 'NO\n' | bash "$ROOT/bin/maho-recovery" rollback-runtime >"$TMP/cancel.out" 2>&1
cancel_rc=$?
set -e
[ "$cancel_rc" -eq 2 ] || { echo "FAIL cancellation returned $cancel_rc" >&2; cat "$TMP/cancel.out" >&2; exit 1; }
grep -Fq 'Cancelled. No recovery action was performed.' "$TMP/cancel.out"
[ ! -s "$SETUP_LOG" ] || { echo 'FAIL cancelled rollback invoked setup' >&2; exit 1; }
echo 'PASS critical runtime rollback requires explicit confirmation'

bash "$ROOT/bin/maho-recovery" rollback-runtime --yes >"$TMP/confirmed.out"
[ "$(cat "$SETUP_LOG")" = rollback ] || { echo 'FAIL confirmed rollback did not invoke exact setup rollback action' >&2; exit 1; }
grep -Fq 'does not modify personal files' "$TMP/confirmed.out"
echo 'PASS explicit confirmation delegates only to scoped runtime rollback'

: >"$SETUP_LOG"
cat >"$TMP/failure.json" <<'EOF_FAILURE'
{"failure":{"domain":"unknown"}}
EOF_FAILURE
plan="$(bash "$ROOT/bin/maho-recovery" plan "$TMP/failure.json")"
[ "$plan" = '{"action":"diagnose-only"}' ]
[ ! -s "$SETUP_LOG" ] || { echo 'FAIL recovery planning invoked setup' >&2; exit 1; }
grep -Fxq "plan $TMP/failure.json" "$PLATFORM_LOG"
echo 'PASS recovery planning delegates to pure policy without mutation'

echo '=== recovery snapshot overlay contracts ==='
bash "$ROOT/tests/recovery-overlay.sh"

echo 'ALL RECOVERY CONSOLE CONTRACTS PASS'
