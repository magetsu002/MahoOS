#!/usr/bin/env bash

maho_decision_die() {
    echo "maho-decision: $*" >&2
    return 1
}

maho_decision_valid_name() {
    [[ "${1:-}" =~ ^[a-z0-9._-]+$ ]]
}

maho_decision_create() {
    local domain="${1:-}"
    local policy="${2:-}"
    local action="${3:-}"
    local resource="${4:-}"
    local reason="${5:-}"
    local evidence_json="${6:-}"
    local desired_json="${7:-}"

    [ -n "$evidence_json" ] || evidence_json='{}'
    [ -n "$desired_json" ] || desired_json='{}'

    maho_decision_valid_name "$domain" || {
        maho_decision_die "invalid domain: $domain"
        return 1
    }
    maho_decision_valid_name "$policy" || {
        maho_decision_die "invalid policy: $policy"
        return 1
    }

    case "$action" in
        do-nothing|adapt|propose)
            ;;
        *)
            maho_decision_die "invalid action: $action"
            return 1
            ;;
    esac

    if [ -n "$resource" ]; then
        maho_decision_valid_name "$resource" || {
            maho_decision_die "invalid resource: $resource"
            return 1
        }
    fi

    [ -n "$reason" ] || {
        maho_decision_die "reason is required"
        return 1
    }

    python - \
        "$domain" "$policy" "$action" "$resource" "$reason" \
        "$evidence_json" "$desired_json" <<'PY'
import json
import sys

(
    domain,
    policy,
    action,
    resource,
    reason,
    evidence_raw,
    desired_raw,
) = sys.argv[1:]

try:
    evidence = json.loads(evidence_raw)
    desired = json.loads(desired_raw)
except Exception as exc:
    raise SystemExit(f"invalid decision JSON payload: {exc}")

if not isinstance(evidence, dict):
    raise SystemExit("decision evidence must be a JSON object")
if not isinstance(desired, dict):
    raise SystemExit("decision desired state must be a JSON object")

payload = {
    "version": 1,
    "domain": domain,
    "policy": policy,
    "action": action,
    "resource": resource or None,
    "reason": reason,
    "evidence": evidence,
    "desired": desired,
}

print(json.dumps(payload, sort_keys=True))
PY
}

maho_decision_validate() {
    local decision_json="${1:-}"

    [ -n "$decision_json" ] || {
        maho_decision_die "decision JSON is required"
        return 1
    }

    python - "$decision_json" <<'PY'
import json
import re
import sys

try:
    d = json.loads(sys.argv[1])
except Exception as exc:
    raise SystemExit(f"invalid decision JSON: {exc}")

if d.get("version") != 1:
    raise SystemExit("unsupported decision version")

name = re.compile(r"^[a-z0-9._-]+$")
for key in ("domain", "policy"):
    value = d.get(key)
    if not isinstance(value, str) or not name.fullmatch(value):
        raise SystemExit(f"invalid decision {key}")

if d.get("action") not in {"do-nothing", "adapt", "propose"}:
    raise SystemExit("invalid decision action")

resource = d.get("resource")
if resource is not None and (
    not isinstance(resource, str) or not name.fullmatch(resource)
):
    raise SystemExit("invalid decision resource")

if not isinstance(d.get("reason"), str) or not d["reason"].strip():
    raise SystemExit("invalid decision reason")
if not isinstance(d.get("evidence"), dict):
    raise SystemExit("invalid decision evidence")
if not isinstance(d.get("desired"), dict):
    raise SystemExit("invalid decision desired state")

print(json.dumps(d, sort_keys=True))
PY
}

maho_decision_pretty() {
    local decision_json="${1:-}"
    decision_json="$(maho_decision_validate "$decision_json")" || return 1

    python - "$decision_json" <<'PY'
import json
import sys

d = json.loads(sys.argv[1])
print("Maho policy decision")
print()
print(f"Domain:   {d['domain']}")
print(f"Policy:   {d['policy']}")
print(f"Action:   {d['action']}")
print(f"Resource: {d['resource'] or 'none'}")
print()
print("Reason:")
print(f"  {d['reason']}")

if d["evidence"]:
    print()
    print("Evidence:")
    for key in sorted(d["evidence"]):
        value = d["evidence"][key]
        if isinstance(value, (dict, list)):
            value = json.dumps(value, sort_keys=True)
        print(f"  {key}: {value}")

if d["desired"]:
    print()
    print("Desired state:")
    for key in sorted(d["desired"]):
        value = d["desired"][key]
        if isinstance(value, (dict, list)):
            value = json.dumps(value, sort_keys=True)
        print(f"  {key}: {value}")
PY
}
