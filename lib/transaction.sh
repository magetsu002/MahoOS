#!/usr/bin/env bash

MAHO_TRANSACTION_ROOT="${MAHO_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)}"
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

maho_transaction_adapter_available() {
    local adapter="${1:-}"

    case "$adapter" in
        /*)
            ;;
        *)
            return 1
            ;;
    esac

    [ -f "$adapter" ] || return 1

    if [ -x "$adapter" ]; then
        return 0
    fi

    case "$adapter" in
        *.sh)
            [ -r "$adapter" ]
            ;;
        *)
            return 1
            ;;
    esac
}

maho_transaction_adapter_call() {
    local adapter="$1"
    shift

    if [ -x "$adapter" ]; then
        MAHO_CYCLE_ID="${MAHO_CYCLE_ID:-}" "$adapter" "$@"
    else
        MAHO_CYCLE_ID="${MAHO_CYCLE_ID:-}" bash "$adapter" "$@"
    fi
}

maho_transaction_rollback() {
    local cycle="$1"
    local adapter="$2"
    local before="$3"
    local domain="$4"
    local resource="$5"
    local adapter_name="$6"
    local cause="$7"

    if ! MAHO_CYCLE_ID="$cycle" maho_transaction_adapter_call "$adapter" rollback "$before"; then
        maho_transaction_emit "$cycle" "$domain" adapter.rollback failed high \
            "Rollback command failed after $cause" "$resource" "$adapter_name" '{}'
        return 1
    fi

    if ! MAHO_CYCLE_ID="$cycle" maho_transaction_adapter_call "$adapter" verify-rollback "$before"; then
        maho_transaction_emit "$cycle" "$domain" adapter.rollback failed high \
            "Rollback command returned success but previous state could not be verified after $cause" \
            "$resource" "$adapter_name" '{}'
        return 1
    fi

    maho_transaction_emit "$cycle" "$domain" adapter.rollback rolled_back low \
        "Previous state restored and verified after $cause" "$resource" "$adapter_name" '{}'
    return 0
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

    maho_transaction_adapter_available "$adapter" || {
        maho_transaction_die "adapter is unavailable: $adapter"
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

    cycle="${MAHO_TRANSACTION_CYCLE_ID:-}"
    if [ -n "$cycle" ]; then
        declare -F maho_cycle_valid >/dev/null 2>&1 && maho_cycle_valid "$cycle" || {
            maho_transaction_die "invalid supplied cycle id: $cycle"
            return 1
        }
    else
        cycle="$(maho_cycle_new "$domain")" || return 1
    fi

    adapter_name="$(basename -- "$adapter")"

    before="$(MAHO_CYCLE_ID="$cycle" maho_transaction_adapter_call "$adapter" capture "$desired")" || {
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

    if ! MAHO_CYCLE_ID="$cycle" maho_transaction_adapter_call "$adapter" apply "$desired"; then
        maho_transaction_emit "$cycle" "$domain" adapter.apply failed low \
            "Adapter apply step failed" "$resource" "$adapter_name" '{}'

        maho_transaction_rollback \
            "$cycle" "$adapter" "$before" "$domain" "$resource" "$adapter_name" \
            "apply failure" || true
        return 1
    fi

    maho_transaction_emit "$cycle" "$domain" adapter.apply observed info \
        "Adapter mutation applied; verification pending" "$resource" "$adapter_name" '{}'

    if MAHO_CYCLE_ID="$cycle" maho_transaction_adapter_call "$adapter" verify "$desired"; then
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

    maho_transaction_rollback \
        "$cycle" "$adapter" "$before" "$domain" "$resource" "$adapter_name" \
        "verification failure" || true

    return 1
}
