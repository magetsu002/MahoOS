#!/usr/bin/env bash

MAHO_STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/maho/state"

maho_state_die() {
    echo "maho-state: $*" >&2
    return 1
}

maho_state_valid_name() {
    [[ "${1:-}" =~ ^[a-z0-9._-]+$ ]]
}

maho_state_publish() {
    local domain="${1:-}"
    local provider="${2:-}"
    local data_json="${3:-}"

    [ -n "$data_json" ] || data_json='{}'

    maho_state_valid_name "$domain" || {
        maho_state_die "invalid domain: $domain"
        return 1
    }

    maho_state_valid_name "$provider" || {
        maho_state_die "invalid provider: $provider"
        return 1
    }

    mkdir -p "$MAHO_STATE_DIR"

    python - "$MAHO_STATE_DIR" "$domain" "$provider" "$data_json" <<'PY'
import datetime as dt
import json
import os
import sys
from pathlib import Path

state_dir = Path(sys.argv[1])
domain = sys.argv[2]
provider = sys.argv[3]

try:
    data = json.loads(sys.argv[4])
except Exception as exc:
    raise SystemExit(f"invalid state JSON: {exc}")

if not isinstance(data, dict):
    raise SystemExit("state data must be a JSON object")

payload = {
    "version": 1,
    "domain": domain,
    "provider": provider,
    "observed_at": dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
    "data": data,
}

state_dir.mkdir(parents=True, exist_ok=True)
path = state_dir / f"{domain}.json"
tmp = state_dir / f".{domain}.{os.getpid()}.tmp"

tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
os.replace(tmp, path)

print(path)
PY
}

maho_state_get() {
    local domain="${1:-}"

    maho_state_valid_name "$domain" || {
        maho_state_die "invalid domain: $domain"
        return 1
    }

    local file="$MAHO_STATE_DIR/$domain.json"

    [ -f "$file" ] || {
        maho_state_die "no state for domain: $domain"
        return 1
    }

    python - "$file" <<'PY'
import json
import sys

with open(sys.argv[1]) as f:
    data = json.load(f)

if data.get("version") != 1:
    raise SystemExit("unsupported state version")

print(json.dumps(data, indent=2, sort_keys=True))
PY
}

maho_state_list() {
    python - "$MAHO_STATE_DIR" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])

if not root.is_dir():
    raise SystemExit(0)

for path in sorted(root.glob("*.json")):
    try:
        data = json.loads(path.read_text())
    except Exception:
        continue

    if data.get("version") != 1:
        continue

    print(
        f"{data.get('domain', path.stem):<24} "
        f"provider={data.get('provider', 'unknown'):<16} "
        f"observed={data.get('observed_at', 'unknown')}"
    )
PY
}
