#!/usr/bin/env bash

maho_cycle_new() {
    local domain="${1:-adaptation}"

    [[ "$domain" =~ ^[a-z0-9._-]+$ ]] || {
        echo "maho-cycle: invalid domain: $domain" >&2
        return 1
    }

    python - "$domain" <<'PY'
import datetime as dt
import sys
import uuid

domain = sys.argv[1]
now = dt.datetime.now(dt.timezone.utc)
print(
    "cyc-"
    + domain
    + "-"
    + now.strftime("%Y%m%dT%H%M%S")
    + "-"
    + uuid.uuid4().hex[:10]
)
PY
}

maho_cycle_valid() {
    [[ "${1:-}" =~ ^cyc-[a-z0-9._-]+-[0-9]{8}T[0-9]{6}-[a-f0-9]{10}$ ]]
}
