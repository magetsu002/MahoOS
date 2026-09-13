#!/usr/bin/env bash
set -u
ROOT="${MAHO_ROOT:-$HOME/Projects/Maho-OS}"
NOTIFY="${MAHO_NOTIFY_BIN:-$ROOT/bin/maho-notify}"

die() { echo "adaptive-quiet-adapter: $*" >&2; return 1; }

normalize_desired() {
    python - "${1:-}" <<'PY_INNER'
import json,sys
try: d=json.loads(sys.argv[1])
except Exception as exc: raise SystemExit(f"invalid desired state: {exc}")
if set(d) != {"operation","enabled"} or d.get("operation") != "set-adaptive-notify-quiet" or not isinstance(d.get("enabled"),bool):
    raise SystemExit("desired state must contain exact set-adaptive-notify-quiet boolean")
print("on" if d["enabled"] else "off")
PY_INNER
}

current_word() {
    [ -r "$NOTIFY" ] || return 1
    bash "$NOTIFY" adaptive-quiet status 2>/dev/null
}

capture() {
    local current
    current="$(current_word)" || return 1
    case "$current" in on|off) ;; *) return 1 ;; esac
    python - "$current" <<'PY_INNER'
import json,sys
print(json.dumps({"enabled":sys.argv[1]=="on"},sort_keys=True))
PY_INNER
}

apply_desired() {
    local desired="$1" target
    target="$(normalize_desired "$desired")" || return 1
    bash "$NOTIFY" adaptive-quiet "$target" >/dev/null
}

verify_desired() {
    local desired="$1" target observed
    target="$(normalize_desired "$desired")" || return 1
    observed="$(current_word)" || return 1
    [ "$observed" = "$target" ]
}

rollback() {
    local before="${1:-}" target
    target="$(python - "$before" <<'PY_INNER'
import json,sys
try: d=json.loads(sys.argv[1])
except Exception as exc: raise SystemExit(f"invalid rollback state: {exc}")
if set(d) != {"enabled"} or not isinstance(d.get("enabled"),bool): raise SystemExit("invalid rollback state")
print("on" if d["enabled"] else "off")
PY_INNER
)" || return 1
    bash "$NOTIFY" adaptive-quiet "$target" >/dev/null
}

verify_rollback() {
    local before="${1:-}" target observed
    target="$(python - "$before" <<'PY_INNER'
import json,sys
d=json.loads(sys.argv[1])
if set(d) != {"enabled"} or not isinstance(d.get("enabled"),bool): raise SystemExit(1)
print("on" if d["enabled"] else "off")
PY_INNER
)" || return 1
    observed="$(current_word)" || return 1
    [ "$observed" = "$target" ]
}

case "${1:-}" in
    capture) capture "${2:-}" ;;
    apply) apply_desired "${2:-}" ;;
    verify) verify_desired "${2:-}" ;;
    rollback) rollback "${2:-}" ;;
    verify-rollback) verify_rollback "${2:-}" ;;
    *) die "expected capture, apply, verify, rollback, or verify-rollback"; exit 2 ;;
esac
