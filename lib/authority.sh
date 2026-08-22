#!/usr/bin/env bash

MAHO_AUTHORITY_ROOT="${MAHO_ROOT:-$HOME/Projects/Maho-OS}"
MAHO_OWNERSHIP_DEFAULTS="$MAHO_AUTHORITY_ROOT/config/ownership.json"
MAHO_OWNERSHIP_OVERRIDES="${XDG_CONFIG_HOME:-$HOME/.config}/maho/ownership.json"

maho_authority_die() {
    echo "maho-authority: $*" >&2
    return 1
}

maho_owner_valid_resource() {
    [[ "${1:-}" =~ ^[a-z0-9._-]+$ ]]
}

maho_owner_valid_value() {
    case "${1:-}" in
        maho|integration|user)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

maho_owner_validate_file() {
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
    raise SystemExit(f"unsupported ownership registry version: {path}")

resources = data.get("resources")
if not isinstance(resources, dict):
    raise SystemExit(f"ownership registry resources must be an object: {path}")

resource_re = re.compile(r"^[a-z0-9._-]+$")
valid_owners = {"maho", "integration", "user"}

for resource, owner in resources.items():
    if not isinstance(resource, str) or not resource_re.fullmatch(resource):
        raise SystemExit(f"invalid ownership resource {resource!r}: {path}")
    if owner not in valid_owners:
        raise SystemExit(f"invalid owner {owner!r} for {resource}: {path}")
PY
}

maho_owner_get() {
    local resource="${1:-}"

    maho_owner_valid_resource "$resource" || {
        maho_authority_die "invalid resource: $resource"
        return 1
    }

    maho_owner_validate_file "$MAHO_OWNERSHIP_DEFAULTS" || return 1
    maho_owner_validate_file "$MAHO_OWNERSHIP_OVERRIDES" || return 1

    python - \
        "$MAHO_OWNERSHIP_DEFAULTS" \
        "$MAHO_OWNERSHIP_OVERRIDES" \
        "$resource" <<'PY'
import json
import sys
from pathlib import Path

def load(path):
    p = Path(path)
    if not p.is_file():
        return {}
    return json.loads(p.read_text()).get("resources", {})

defaults = load(sys.argv[1])
overrides = load(sys.argv[2])
resource = sys.argv[3]

if resource in overrides:
    print(overrides[resource])
elif resource in defaults:
    print(defaults[resource])
else:
    # Safety default: Maho never claims an unknown resource.
    print("user")
PY
}

maho_owner_set() {
    local resource="${1:-}"
    local owner="${2:-}"

    maho_owner_valid_resource "$resource" || {
        maho_authority_die "invalid resource: $resource"
        return 1
    }

    maho_owner_valid_value "$owner" || {
        maho_authority_die "owner must be maho, integration, or user"
        return 1
    }

    mkdir -p "$(dirname -- "$MAHO_OWNERSHIP_OVERRIDES")"

    python - "$MAHO_OWNERSHIP_OVERRIDES" "$resource" "$owner" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
resource = sys.argv[2]
owner = sys.argv[3]

if path.is_file():
    data = json.loads(path.read_text())
else:
    data = {"version": 1, "resources": {}}

if data.get("version") != 1:
    raise SystemExit("unsupported ownership registry version")

resources = data.setdefault("resources", {})
if not isinstance(resources, dict):
    raise SystemExit("ownership registry resources must be an object")

resources[resource] = owner

tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
os.replace(tmp, path)
PY

    printf '%s = %s\n' "$resource" "$owner"
}

maho_owner_unset() {
    local resource="${1:-}"

    maho_owner_valid_resource "$resource" || {
        maho_authority_die "invalid resource: $resource"
        return 1
    }

    [ -f "$MAHO_OWNERSHIP_OVERRIDES" ] || return 0

    python - "$MAHO_OWNERSHIP_OVERRIDES" "$resource" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
resource = sys.argv[2]
data = json.loads(path.read_text())

if data.get("version") != 1:
    raise SystemExit("unsupported ownership registry version")

resources = data.setdefault("resources", {})
resources.pop(resource, None)

tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
os.replace(tmp, path)
PY
}

maho_owner_list() {
    maho_owner_validate_file "$MAHO_OWNERSHIP_DEFAULTS" || return 1
    maho_owner_validate_file "$MAHO_OWNERSHIP_OVERRIDES" || return 1

    python - \
        "$MAHO_OWNERSHIP_DEFAULTS" \
        "$MAHO_OWNERSHIP_OVERRIDES" <<'PY'
import json
import sys
from pathlib import Path

def load(path):
    p = Path(path)
    if not p.is_file():
        return {}
    return json.loads(p.read_text()).get("resources", {})

defaults = load(sys.argv[1])
overrides = load(sys.argv[2])
resources = sorted(set(defaults) | set(overrides))

if not resources:
    print("(no declared resources; unknown resources default to user)")
    raise SystemExit

for resource in resources:
    if resource in overrides:
        owner = overrides[resource]
        source = "user override"
    else:
        owner = defaults[resource]
        source = "Maho default"

    print(f"{resource} = {owner} ({source})")
PY
}

maho_owner_can_auto() {
    [ "$(maho_owner_get "$1")" = "maho" ]
}
