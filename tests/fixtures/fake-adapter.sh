#!/usr/bin/env bash

set -euo pipefail

STATE="${MAHO_TEST_ADAPTER_STATE:?MAHO_TEST_ADAPTER_STATE required}"
cmd="${1:-}"
payload="${2:-}"

verify_payload() {
    python - "$payload" "$STATE" <<'PY'
import json,sys
from pathlib import Path
expected=json.loads(sys.argv[1])
actual=json.loads(Path(sys.argv[2]).read_text())
raise SystemExit(0 if actual == expected else 1)
PY
}

case "$cmd" in
    capture)
        cat "$STATE"
        ;;
    apply)
        python - "$payload" "$STATE" <<'PY'
import json,sys
from pathlib import Path
value=json.loads(sys.argv[1])
Path(sys.argv[2]).write_text(json.dumps(value,sort_keys=True)+"\n")
PY
        ;;
    verify)
        verify_payload
        ;;
    rollback)
        python - "$payload" "$STATE" <<'PY'
import json,sys
from pathlib import Path
value=json.loads(sys.argv[1])
Path(sys.argv[2]).write_text(json.dumps(value,sort_keys=True)+"\n")
PY
        ;;
    verify-rollback)
        verify_payload
        ;;
    *)
        exit 2
        ;;
esac
