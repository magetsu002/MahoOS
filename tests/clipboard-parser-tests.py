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


def run_backend(
    environment: dict[str, str], *arguments: str
) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, str(BACKEND), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    return json.loads(result.stdout)


# Pinning owns payload bytes outside cliphist so a service restart, eviction,
# or ordinary wipe cannot silently destroy a user-pinned item.
with tempfile.TemporaryDirectory() as temporary:
    base = Path(temporary)
    binaries = base / "bin"
    payloads = base / "cliphist-payloads"
    state = base / "state"
    history_file = base / "history.txt"
    captured = base / "captured.bin"
    binaries.mkdir()
    payloads.mkdir()

    cliphist = binaries / "cliphist"
    cliphist.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys\n"
        "history = pathlib.Path(os.environ['FAKE_HISTORY'])\n"
        "payloads = pathlib.Path(os.environ['FAKE_PAYLOADS'])\n"
        "command = sys.argv[1] if len(sys.argv) > 1 else ''\n"
        "if command == 'list':\n"
        "    sys.stdout.write(history.read_text())\n"
        "elif command == 'decode' and len(sys.argv) == 3:\n"
        "    path = payloads / sys.argv[2]\n"
        "    if not path.is_file(): raise SystemExit(4)\n"
        "    sys.stdout.buffer.write(path.read_bytes())\n"
        "elif command == 'wipe':\n"
        "    history.write_text('')\n"
        "else:\n"
        "    raise SystemExit(2)\n",
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
        "XDG_STATE_HOME": str(state),
        "FAKE_HISTORY": str(history_file),
        "FAKE_PAYLOADS": str(payloads),
        "CAPTURED": str(captured),
    })

    first_payload = b"persistent pinned payload\nwith exact bytes\x00"
    second_payload = b"ordinary unpinned item"
    (payloads / "10").write_bytes(first_payload)
    (payloads / "9").write_bytes(second_payload)
    history_file.write_text("10\tpersistent pinned payload\n9\tordinary unpinned item\n")

    pinned = run_backend(environment, "pin", "10")
    assert pinned["ok"] is True
    pin_key = str(pinned["pinKey"])
    assert pin_key == MODULE.hashlib.sha256(first_payload).hexdigest()

    # A fresh backend process represents a UI/service restart. The pinned item
    # is first and its live cliphist copy is not duplicated.
    listed = run_backend(environment, "list")
    assert [item["pinned"] for item in listed["items"]] == [True, False]
    assert [item["preview"] for item in listed["items"]] == [
        "persistent pinned payload", "ordinary unpinned item"
    ]
    assert listed["items"][0]["section"] == "Pinned"

    # Copying the same content can produce a new cliphist id. Matching payload
    # identity still yields one item, never a pinned + normal duplicate.
    (payloads / "11").write_bytes(first_payload)
    history_file.write_text("11\tpersistent pinned payload\n9\tordinary unpinned item\n")
    deduplicated = run_backend(environment, "list")
    assert len([item for item in deduplicated["items"] if item["preview"] == "persistent pinned payload"]) == 1

    # Simulate normal cliphist max-item eviction. The pin store remains the
    # source of truth and selection restores the exact bytes.
    history_file.write_text("")
    after_eviction = run_backend(environment, "list")
    assert len(after_eviction["items"]) == 1
    assert after_eviction["items"][0]["id"] == f"pin:{pin_key}"
    assert run_backend(environment, "select", f"pin:{pin_key}") == {"ok": True, "error": ""}
    assert captured.read_bytes() == first_payload

    # Ordinary clear delegates to cliphist wipe and cannot touch the explicit
    # pin directory. Only explicit unpin removes that payload.
    (payloads / "12").write_bytes(second_payload)
    history_file.write_text("12\tordinary unpinned item\n")
    assert run_backend(environment, "clear") == {"ok": True, "error": ""}
    assert history_file.read_text() == ""
    after_clear = run_backend(environment, "list")
    assert [item["id"] for item in after_clear["items"]] == [f"pin:{pin_key}"]
    assert run_backend(environment, "unpin", pin_key) == {"ok": True, "error": ""}
    assert run_backend(environment, "list")["items"] == []

    index = state / "maho/clipboard/pins/index.json"
    assert index.stat().st_mode & 0o777 == 0o600

print("PASS  clipboard pin persistence, deduplication, eviction, and clear behavior")
