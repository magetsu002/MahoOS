#!/usr/bin/env bash

MAHO_TRANSACTION_ROOT="${MAHO_ROOT:-$HOME/Projects/Maho-OS}"
MAHO_TRANSACTION_EVENTS="$MAHO_TRANSACTION_ROOT/lib/events.sh"
MAHO_TRANSACTION_CYCLES="$MAHO_TRANSACTION_ROOT/lib/cycle.sh"

[ -r "$MAHO_TRANSACTION_EVENTS" ] && source "$MAHO_TRANSACTION_EVENTS"
[ -r "$MAHO_TRANSACTION_CYCLES" ] && source "$MAHO_TRANSACTION_CYCLES"

maho_transaction_die() {
    echo "maho-transaction: $*" >&2
    return 1
}

maho_transaction_json_object() {
    local value="${1:-}"

    python - "$value" <<'PY'
import json
import sys

try:
    value = json.loads(sys.argv[1])
except Exception as exc:
    raise SystemExit(f"invalid JSON: {exc}")

if not isinstance(value, dict):
    raise SystemExit("transaction payload must be a JSON object")

print(json.dumps(value, sort_keys=True))
PY
}

maho_transaction_emit() {
    local cycle_id="$1"
    shift

    if declare -F maho_event_emit >/dev/null 2>&1; then
        MAHO_CYCLE_ID="$cycle_id" maho_event_emit "$@" >/dev/null 2>&1 || true
    fi
}

maho_transaction_execute() {
    local adapter="${1:-}"
    local desired_raw="${2:-}"
    local domain="${3:-adaptation}"
    local resource="${4:-}"

    [ -n "$adapter" ] || {
        maho_transaction_die "adapter path is required"
        return 1
    }

    case "$adapter" in
        /*)
            ;;
        *)
            maho_transaction_die "adapter path must be absolute"
            return 1
            ;;
    esac

    [ -x "$adapter" ] || {
        maho_transaction_die "adapter is not executable: $adapter"
        return 1
    }

    [[ "$domain" =~ ^[a-z0-9._-]+$ ]] || {
        maho_transaction_die "invalid domain: $domain"
        return 1
    }

    if [ -n "$resource" ] && ! [[ "$resource" =~ ^[a-z0-9._-]+$ ]]; then
        maho_transaction_die "invalid resource: $resource"
        return 1
    fi

    local desired before cycle adapter_name
    desired="$(maho_transaction_json_object "$desired_raw")" || return 1

    declare -F maho_cycle_new >/dev/null 2>&1 || {
        maho_transaction_die "cycle layer unavailable"
        return 1
    }

    cycle="$(maho_cycle_new "$domain")" || return 1
    adapter_name="$(basename -- "$adapter")"

    before="$(MAHO_CYCLE_ID="$cycle" "$adapter" capture "$desired")" || {
        maho_transaction_emit "$cycle" "$domain" adapter.capture failed low \
            "Adapter failed to capture pre-mutation state" "$resource" "$adapter_name" \
            "$(python - "$adapter" <<'PY'
import json, sys
print(json.dumps({"adapter": sys.argv[1]}))
PY
)"
        return 1
    }

    before="$(maho_transaction_json_object "$before")" || {
        maho_transaction_emit "$cycle" "$domain" adapter.capture failed low \
            "Adapter returned an invalid pre-mutation state" "$resource" "$adapter_name" '{}'
        return 1
    }

    maho_transaction_emit "$cycle" "$domain" adapter.capture observed info \
        "Captured pre-mutation state" "$resource" "$adapter_name" \
        "$(python - "$adapter" <<'PY'
import json, sys
print(json.dumps({"adapter": sys.argv[1]}))
PY
)"

    if ! MAHO_CYCLE_ID="$cycle" "$adapter" apply "$desired"; then
        maho_transaction_emit "$cycle" "$domain" adapter.apply failed low \
            "Adapter apply step failed" "$resource" "$adapter_name" '{}'

        if MAHO_CYCLE_ID="$cycle" "$adapter" rollback "$before"; then
            maho_transaction_emit "$cycle" "$domain" adapter.rollback rolled_back low \
                "Previous state restored after apply failure" "$resource" "$adapter_name" '{}'
        else
            maho_transaction_emit "$cycle" "$domain" adapter.rollback failed high \
                "Rollback failed after adapter apply failure" "$resource" "$adapter_name" '{}'
        fi
        return 1
    fi

    maho_transaction_emit "$cycle" "$domain" adapter.apply observed info \
        "Adapter mutation applied; verification pending" "$resource" "$adapter_name" '{}'

    if MAHO_CYCLE_ID="$cycle" "$adapter" verify "$desired"; then
        maho_transaction_emit "$cycle" "$domain" adapter.verify verified info \
            "Adapter mutation verified against desired state" "$resource" "$adapter_name" '{}'

        python - "$cycle" "$adapter" "$domain" "$resource" "$desired" "$before" <<'PY'
import json
import sys

cycle, adapter, domain, resource, desired_raw, before_raw = sys.argv[1:]
print(json.dumps({
    "version": 1,
    "cycle_id": cycle,
    "status": "verified",
    "adapter": adapter,
    "domain": domain,
    "resource": resource or None,
    "desired": json.loads(desired_raw),
    "before": json.loads(before_raw),
}, sort_keys=True))
PY
        return 0
    fi

    maho_transaction_emit "$cycle" "$domain" adapter.verify failed low \
        "Adapter mutation failed verification" "$resource" "$adapter_name" '{}'

    if MAHO_CYCLE_ID="$cycle" "$adapter" rollback "$before"; then
        maho_transaction_emit "$cycle" "$domain" adapter.rollback rolled_back low \
            "Previous state restored after verification failure" "$resource" "$adapter_name" '{}'
    else
        maho_transaction_emit "$cycle" "$domain" adapter.rollback failed high \
            "Rollback failed after verification failure" "$resource" "$adapter_name" '{}'
    fi

    return 1
}
