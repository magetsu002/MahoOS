#!/usr/bin/env bash

MAHO_EVENT_LOG="${XDG_STATE_HOME:-$HOME/.local/state}/maho/history/events.jsonl"

maho_event_die() {
    echo "maho-events: $*" >&2
    return 1
}

maho_event_valid_name() {
    [[ "${1:-}" =~ ^[a-z0-9._-]+$ ]]
}

maho_event_emit() {
    local domain="${1:-}"
    local kind="${2:-}"
    local status="${3:-}"
    local risk="${4:-info}"
    local summary="${5:-}"
    local resource="${6:-}"
    local source="${7:-}"
    local details_json="${8:-{}}"

    maho_event_valid_name "$domain" || {
        maho_event_die "invalid domain: $domain"
        return 1
    }

    maho_event_valid_name "$kind" || {
        maho_event_die "invalid kind: $kind"
        return 1
    }

    [ -n "$summary" ] || {
        maho_event_die "summary is required"
        return 1
    }

    mkdir -p "$(dirname "$MAHO_EVENT_LOG")"

    python - \
        "$MAHO_EVENT_LOG" \
        "$domain" \
        "$kind" \
        "$status" \
        "$risk" \
        "$summary" \
        "$resource" \
        "$source" \
        "$details_json" <<'PY'
import datetime as dt
import fcntl
import json
import os
import sys
import uuid
from pathlib import Path

(
    log_path,
    domain,
    kind,
    status,
    risk,
    summary,
    resource,
    source,
    details_raw,
) = sys.argv[1:]

valid_status = {
    "observed",
    "skipped",
    "proposed",
    "verified",
    "failed",
    "rolled_back",
    "contained",
    "recovered",
}
valid_risk = {"info", "low", "medium", "high", "critical"}

if status not in valid_status:
    raise SystemExit(f"invalid event status: {status}")
if risk not in valid_risk:
    raise SystemExit(f"invalid event risk: {risk}")

try:
    details = json.loads(details_raw)
except Exception as exc:
    raise SystemExit(f"invalid event details JSON: {exc}")

if not isinstance(details, dict):
    raise SystemExit("event details must be a JSON object")

now = dt.datetime.now(dt.timezone.utc)
event_id = "evt-" + now.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:10]

payload = {
    "version": 1,
    "id": event_id,
    "at": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    "domain": domain,
    "kind": kind,
    "status": status,
    "risk": risk,
    "summary": summary,
    "resource": resource or None,
    "source": source or None,
    "details": details,
}

path = Path(log_path)
path.parent.mkdir(parents=True, exist_ok=True)
line = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"

with path.open("a", encoding="utf-8") as f:
    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    f.write(line)
    f.flush()
    os.fsync(f.fileno())
    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

print(event_id)
PY
}

maho_event_tail() {
    local count="${1:-20}"

    [[ "$count" =~ ^[0-9]+$ ]] || {
        maho_event_die "count must be a non-negative integer"
        return 1
    }

    python - "$MAHO_EVENT_LOG" "$count" <<'PY'
import json
import sys
from collections import deque
from pathlib import Path

path = Path(sys.argv[1])
count = int(sys.argv[2])

if not path.is_file() or count == 0:
    raise SystemExit(0)

lines = deque(maxlen=count)
with path.open() as f:
    for line in f:
        line = line.strip()
        if line:
            lines.append(line)

for line in lines:
    data = json.loads(line)
    print(
        f"{data.get('at', 'unknown')}  "
        f"{data.get('domain', 'unknown'):<12} "
        f"{data.get('status', 'unknown'):<11} "
        f"{data.get('kind', 'unknown'):<28} "
        f"{data.get('summary', '')}"
    )
PY
}

maho_event_last() {
    local domain="${1:-}"

    if [ -n "$domain" ]; then
        maho_event_valid_name "$domain" || {
            maho_event_die "invalid domain: $domain"
            return 1
        }
    fi

    python - "$MAHO_EVENT_LOG" "$domain" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
domain = sys.argv[2]

if not path.is_file():
    raise SystemExit(1)

last = None
with path.open() as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except Exception:
            continue
        if data.get("version") != 1:
            continue
        if domain and data.get("domain") != domain:
            continue
        last = data

if last is None:
    raise SystemExit(1)

print(json.dumps(last, indent=2, sort_keys=True))
PY
}

maho_event_show() {
    local event_id="${1:-}"

    [ -n "$event_id" ] || {
        maho_event_die "event id is required"
        return 1
    }

    python - "$MAHO_EVENT_LOG" "$event_id" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
event_id = sys.argv[2]

if not path.is_file():
    raise SystemExit(1)

with path.open() as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except Exception:
            continue
        if data.get("id") == event_id:
            print(json.dumps(data, indent=2, sort_keys=True))
            raise SystemExit(0)

raise SystemExit(1)
PY
}
