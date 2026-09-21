#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
GUARD="$ROOT/bin/maho-vesktop-guard"
PATCHER="$ROOT/lib/maho_vesktop_patch.py"

bash -n "$GUARD"
python3 -m py_compile "$PATCHER"

python3 - "$PATCHER" "$GUARD" <<'PY'
import importlib.util
from pathlib import Path
import sys

patcher_path = Path(sys.argv[1])
guard_path = Path(sys.argv[2])

spec = importlib.util.spec_from_file_location("maho_vesktop_patch", patcher_path)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

source = (
    "prefix;"
    + module.SECOND_INSTANCE_OLD
    + ";middle;"
    + module.OWNER_ANCHOR
    + "fallback;tail"
)
patched = module.patch_main(source)

assert module.SECOND_INSTANCE_OLD not in patched
assert module.OWNER_ANCHOR not in patched
assert "__mahoVesktopActivate" in patched
assert "__mahoVesktopSetupControl" in patched
assert 'q.action==="activate"' in patched
assert 'q.action==="close"' in patched
assert 'q.action==="hide"' in patched
assert 'q.action==="minimize"' in patched
assert 'q.action==="state"' in patched
assert "chmodSync(s,384)" in patched

try:
    module.patch_main("unexpected Vesktop runtime shape")
except RuntimeError:
    pass
else:
    raise AssertionError("patch mismatch did not fail closed")

guard = guard_path.read_text()
assert 'LOCK="$RUNTIME_DIR/maho-vesktop-profile.lock"' in guard
assert 'SOCKET="$RUNTIME_DIR/maho-vesktop-control.sock"' in guard
assert "profile owner exists but could not be activated" in guard
assert "unmanaged Vesktop profile owner is already running" in guard
assert '*" --type="*) continue ;;' in guard
launch_tail = guard.split('local start_ticks', 1)[1]
launch_tail = launch_tail.split('indexeddb_lock_holders()', 1)[0]
assert "flock -u 9" not in launch_tail
assert 'exec /usr/bin/electron43' in launch_tail
PY

git -C "$ROOT" diff --check

echo "PASS vesktop session reliability contracts"
