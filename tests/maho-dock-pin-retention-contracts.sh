#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL="$ROOT/config/quickshell/maho-shell/MahoDockModel.qml"

grep -Fq -- 'const app = root.appById[id] || null' "$MODEL" || {
    echo "FAIL: temporarily unresolved apps can disappear from persisted pins" >&2
    exit 1
}

python3 - "$MODEL" <<'PY'
from pathlib import Path
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8")
start = text.index("const pins = root.dockState.pins || []")
end = text.index("const runningIds =", start)
pin_rendering = text[start:end]
if "if (!app)" in pin_rendering:
    raise SystemExit(
        "FAIL: Dock discards a persisted pin when app metadata is temporarily unavailable"
    )
if "output.push(makeItem(id, app, grouped[id] || [], true, false))" not in pin_rendering:
    raise SystemExit("FAIL: persisted pins are not rendered independently of running windows")
PY

echo "PASS: persisted pins survive application exit and transient metadata gaps"
