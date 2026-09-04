#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "config/quickshell/maho-clipboard/clipboard.py"
SPEC = importlib.util.spec_from_file_location("maho_clipboard", BACKEND)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


history = (
    "10\tnormal text\n"
    "9\tline one\nline two\nline three\n"
    "8\t\nmeaning after a leading newline\n"
    "7\tfirst\n\n\nlast\n"
    "6\tこんにちは 🌙\n"
    "5\talpha\tbeta\n"
    "4\thttps://example.com/path?q=maho\n"
    "3\tgit status --short\n"
    "2\t[[ binary data 782 KiB png 1270x868 ]]\n"
)
records = MODULE.parse_history_records(history)
assert [item_id for item_id, _ in records] == [str(value) for value in range(10, 1, -1)]
previews = {item_id: MODULE.classify(preview) for item_id, preview in records}

assert previews["10"] == ("Text", "normal text")
assert previews["9"] == ("Text", "line one line two line three")
assert previews["8"] == ("Text", "meaning after a leading newline")
assert previews["7"] == ("Text", "first last")
assert previews["6"] == ("Text", "こんにちは 🌙")
assert previews["5"] == ("Text", "alpha beta")
assert previews["4"] == ("Link", "https://example.com/path?q=maho")
assert previews["3"] == ("Command", "git status --short")
assert previews["2"] == ("Image", "[Image] PNG · 782 KiB · 1270×868")

# Selection must pipe decoded bytes verbatim. The preview is deliberately
# unrelated and cannot be used to reconstruct this payload.
exact = b"\x00first line\nsecond\tline\n\nfinal\xffbyte"
with tempfile.TemporaryDirectory() as temporary:
    base = Path(temporary)
    binaries = base / "bin"
    binaries.mkdir()
    decoded = base / "decoded.bin"
    captured = base / "captured.bin"
    decoded.write_bytes(exact)

    cliphist = binaries / "cliphist"
    cliphist.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys\n"
        "if len(sys.argv) == 3 and sys.argv[1:] == ['decode', '42']:\n"
        "    sys.stdout.buffer.write(pathlib.Path(os.environ['DECODED']).read_bytes())\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(2)\n",
        encoding="utf-8",
    )
    wl_copy = binaries / "wl-copy"
    wl_copy.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys\n"
        "pathlib.Path(os.environ['CAPTURED']).write_bytes(sys.stdin.buffer.read())\n",
        encoding="utf-8",
    )
    cliphist.chmod(0o755)
    wl_copy.chmod(0o755)

    environment = dict(os.environ)
    environment.update({
        "PATH": f"{binaries}:{environment.get('PATH', '')}",
        "DECODED": str(decoded),
        "CAPTURED": str(captured),
    })
    result = subprocess.run(
        [sys.executable, str(BACKEND), "select", "42"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    assert json.loads(result.stdout) == {"ok": True, "error": ""}
    assert captured.read_bytes() == exact

print("PASS  clipboard record parsing and exact byte restore")
