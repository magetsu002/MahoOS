#!/usr/bin/env bash

MAHO_INTENT_ROOT="${MAHO_ROOT:-$HOME/Projects/Maho-OS}"
MAHO_INTENT_DEFAULTS="$MAHO_INTENT_ROOT/config/intent.json"
MAHO_INTENT_OVERRIDES="${XDG_CONFIG_HOME:-$HOME/.config}/maho/intent.json"

maho_intent_die() {
    echo "maho-intent: $*" >&2
    return 1
}

maho_intent_valid_key() {
    [[ "${1:-}" =~ ^[a-z0-9._-]+$ ]]
}

maho_intent_validate_file() {
    local file="$1"

    [ -f "$file" ] || return 0

    python - "$file" <<'PY'
import json
import re
import sys

path = sys.argv[1]

with open(path) as f:
    data = json.load(f)

if data.get("version") != 1:
    raise SystemExit(f"unsupported intent registry version: {path}")

values = data.get("values")
if not isinstance(values, dict):
    raise SystemExit(f"intent registry values must be an object: {path}")

key_re = re.compile(r"^[a-z0-9._-]+$")
for key in values:
    if not isinstance(key, str) or not key_re.fullmatch(key):
        raise SystemExit(f"invalid intent key {key!r}: {path}")
PY
}

maho_intent_get() {
    local key="${1:-}"

    maho_intent_valid_key "$key" || {
        maho_intent_die "invalid key: $key"
        return 1
    }

    maho_intent_validate_file "$MAHO_INTENT_DEFAULTS" || return 1
    maho_intent_validate_file "$MAHO_INTENT_OVERRIDES" || return 1

    python - \
        "$MAHO_INTENT_DEFAULTS" \
        "$MAHO_INTENT_OVERRIDES" \
        "$key" <<'PY'
import json
import sys
from pathlib import Path

def load(path):
    p = Path(path)
    if not p.is_file():
        return {}
    return json.loads(p.read_text()).get("values", {})

defaults = load(sys.argv[1])
overrides = load(sys.argv[2])
key = sys.argv[3]

if key in overrides:
    value = overrides[key]
elif key in defaults:
    value = defaults[key]
else:
    value = None

print(json.dumps(value, sort_keys=True))
PY
}

maho_intent_bool() {
    local key="${1:-}"
    local fallback="${2:-false}"
    local value

    value="$(maho_intent_get "$key")" || return 1

    case "$value" in
        true)
            return 0
            ;;
        false)
            return 1
            ;;
        null)
            [ "$fallback" = "true" ]
            ;;
        *)
            maho_intent_die "$key is not boolean"
            return 2
            ;;
    esac
}

maho_intent_set() {
    local key="${1:-}"
    local value_json="${2:-}"

    maho_intent_valid_key "$key" || {
        maho_intent_die "invalid key: $key"
        return 1
    }

    [ -n "$value_json" ] || {
        maho_intent_die "JSON value is required"
        return 1
    }

    maho_intent_validate_file "$MAHO_INTENT_DEFAULTS" || return 1
    maho_intent_validate_file "$MAHO_INTENT_OVERRIDES" || return 1

    mkdir -p "$(dirname "$MAHO_INTENT_OVERRIDES")"

    python - "$MAHO_INTENT_OVERRIDES" "$key" "$value_json" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]

try:
    value = json.loads(sys.argv[3])
except Exception as exc:
    raise SystemExit(f"intent value must be valid JSON: {exc}")

if path.is_file():
    data = json.loads(path.read_text())
else:
    data = {"version": 1, "values": {}}

if data.get("version") != 1:
    raise SystemExit("unsupported intent registry version")

values = data.setdefault("values", {})
if not isinstance(values, dict):
    raise SystemExit("intent registry values must be an object")

values[key] = value
path.parent.mkdir(parents=True, exist_ok=True)
tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
os.replace(tmp, path)

print(f"{key} = {json.dumps(value, sort_keys=True)}")
PY
}

maho_intent_unset() {
    local key="${1:-}"

    maho_intent_valid_key "$key" || {
        maho_intent_die "invalid key: $key"
        return 1
    }

    [ -f "$MAHO_INTENT_OVERRIDES" ] || return 0

    python - "$MAHO_INTENT_OVERRIDES" "$key" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
data = json.loads(path.read_text())

if data.get("version") != 1:
    raise SystemExit("unsupported intent registry version")

values = data.setdefault("values", {})
values.pop(key, None)

tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
os.replace(tmp, path)
PY
}

maho_intent_list() {
    maho_intent_validate_file "$MAHO_INTENT_DEFAULTS" || return 1
    maho_intent_validate_file "$MAHO_INTENT_OVERRIDES" || return 1

    python - "$MAHO_INTENT_DEFAULTS" "$MAHO_INTENT_OVERRIDES" <<'PY'
import json
import sys
from pathlib import Path

def load(path):
    p = Path(path)
    if not p.is_file():
        return {}
    return json.loads(p.read_text()).get("values", {})

defaults = load(sys.argv[1])
overrides = load(sys.argv[2])

for key in sorted(set(defaults) | set(overrides)):
    if key in overrides:
        value = overrides[key]
        source = "user"
    else:
        value = defaults[key]
        source = "default"

    print(f"{key} = {json.dumps(value, sort_keys=True)}  [{source}]")
PY
}
