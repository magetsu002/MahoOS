#!/usr/bin/env python3

"""Presentation and persistent-pin adapter for cliphist clipboard history.

Normal history remains owned by cliphist. Only items explicitly pinned by the
user are copied into a private XDG state directory so cliphist cleanup cannot
silently evict them. Clipboard payloads are never logged or placed in JSON.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

IMAGE_RE = re.compile(
    r"^\[\[\s*binary data\s+"
    r"(?P<size>\d+(?:\.\d+)?\s*(?:[KMGT]?i?B|B))\s+"
    r"(?P<format>[A-Za-z0-9.+-]+)\s+"
    r"(?P<dims>\d+x\d+)\s*\]\]$",
    re.IGNORECASE,
)
HISTORY_START_RE = re.compile(r"^(?P<id>\d+)\t(?P<preview>.*)$")
URL_RE = re.compile(r"^(?:https?://|www\.)\S+$", re.IGNORECASE)
COMMAND_RE = re.compile(
    r"^(?:\$\s+|\.\/|~\/|/)?(?:"
    r"cd|git|sudo|pacman|yay|paru|python3?|node|npm|pnpm|yarn|cargo|"
    r"make|cmake|ninja|docker|podman|kubectl|ssh|scp|rsync|curl|wget|"
    r"grep|rg|sed|awk|cat|less|head|tail|ls|mkdir|rm|cp|mv|chmod|chown|"
    r"systemctl|journalctl|hyprctl|quickshell|bash|zsh|sh"
    r")(?:\s|$)",
    re.IGNORECASE,
)
PIN_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_PINNED_ITEMS = 100


def emit(payload: dict[str, Any]) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    sys.stdout.write("\n")
    return 0


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def classify(preview: str) -> tuple[str, str]:
    image = IMAGE_RE.match(preview.strip())
    if image:
        image_format = image.group("format").upper()
        if image_format == "JPG":
            image_format = "JPEG"
        dimensions = image.group("dims").replace("x", "×")
        display = f"[Image] {image_format} · {image.group('size')} · {dimensions}"
        return "Image", display

    display = normalize_text(preview)
    if not display:
        display = "Empty text"

    if URL_RE.match(display):
        return "Link", display
    if COMMAND_RE.match(display):
        return "Command", display
    return "Text", display


def parse_history_records(output: str) -> list[tuple[str, str]]:
    """Reconstruct cliphist records without discarding multiline text.

    `cliphist list` prefixes each entry with `<id>\t`, but text payloads may span
    additional physical lines. Treat only a new numeric prefix as a record
    boundary and attach every continuation line to the current preview. This
    keeps leading-newline and multiline clipboard entries meaningful without
    decoding or persisting their full clipboard bytes anywhere else.
    """

    records: list[tuple[str, str]] = []
    current_id: str | None = None
    current_lines: list[str] = []

    for line in output.splitlines():
        match = HISTORY_START_RE.match(line)
        if match:
            if current_id is not None:
                records.append((current_id, "\n".join(current_lines)))
            current_id = match.group("id")
            current_lines = [match.group("preview")]
            continue

        if current_id is not None:
            current_lines.append(line)

    if current_id is not None:
        records.append((current_id, "\n".join(current_lines)))

    return records


def pin_root() -> Path:
    state_home = os.environ.get("XDG_STATE_HOME")
    if state_home:
        return Path(state_home) / "maho" / "clipboard" / "pins"
    return Path.home() / ".local" / "state" / "maho" / "clipboard" / "pins"


def pin_index_path() -> Path:
    return pin_root() / "index.json"


def pin_payload_path(pin_key: str) -> Path:
    return pin_root() / "payloads" / f"{pin_key}.bin"


def ensure_pin_store() -> None:
    root = pin_root()
    payloads = root / "payloads"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    payloads.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    payloads.chmod(0o700)


def load_pins() -> list[dict[str, Any]]:
    try:
        payload = json.loads(pin_index_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []

    source = payload.get("pins", []) if isinstance(payload, dict) else []
    pins: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in source:
        if not isinstance(raw, dict):
            continue
        key = raw.get("key", "")
        if not isinstance(key, str) or not PIN_KEY_RE.fullmatch(key) or key in seen:
            continue
        if not pin_payload_path(key).is_file():
            continue
        preview = raw.get("preview", "Pinned clipboard item")
        item_type = raw.get("type", "Text")
        source_id = raw.get("sourceId", "")
        pinned_at = raw.get("pinnedAt", 0)
        pins.append({
            "key": key,
            "preview": preview if isinstance(preview, str) else "Pinned clipboard item",
            "type": item_type if isinstance(item_type, str) else "Text",
            "sourceId": source_id if isinstance(source_id, str) else "",
            "pinnedAt": pinned_at if isinstance(pinned_at, int) else 0,
        })
        seen.add(key)

    pins.sort(key=lambda item: (-item["pinnedAt"], item["key"]))
    return pins


def save_pins(pins: list[dict[str, Any]]) -> None:
    ensure_pin_store()
    target = pin_index_path()
    payload = json.dumps(
        {"version": 1, "pins": pins},
        ensure_ascii=False,
        separators=(",", ":"),
    ) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".index.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def decode_item(cliphist: str, item_id: str) -> bytes | None:
    try:
        decoded = subprocess.run(
            [cliphist, "decode", item_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=3.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return decoded.stdout if decoded.returncode == 0 else None


def read_cliphist(cliphist: str) -> tuple[bool, list[tuple[str, str]]]:
    try:
        result = subprocess.run(
            [cliphist, "list"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2.5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, []
    if result.returncode != 0:
        return False, []
    return True, parse_history_records(result.stdout)


def item_payload(item_id: str) -> bytes | None:
    if item_id.startswith("pin:"):
        key = item_id.removeprefix("pin:")
        if not PIN_KEY_RE.fullmatch(key):
            return None
        try:
            return pin_payload_path(key).read_bytes()
        except OSError:
            return None

    if not item_id.isdigit():
        return None
    cliphist = shutil.which("cliphist")
    return decode_item(cliphist, item_id) if cliphist else None


def pinned_list_items(pins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "id": f"pin:{pin['key']}",
        "pinKey": pin["key"],
        "pinned": True,
        "section": "Pinned",
        "preview": pin["preview"],
        "type": pin["type"],
        "search": f"{pin['preview']} {pin['type']} pinned".casefold(),
    } for pin in pins]


def list_history() -> int:
    pins = load_pins()
    items = pinned_list_items(pins)
    cliphist = shutil.which("cliphist")
    if not cliphist:
        return emit({
            "available": bool(items),
            "items": items,
            "error": "Clipboard history is unavailable.",
        })

    available, records = read_cliphist(cliphist)
    if not available:
        return emit({
            "available": bool(items),
            "items": items,
            "error": "Clipboard history could not be read.",
        })

    pinned_source_ids = {item["sourceId"] for item in pins if item["sourceId"]}
    pinned_candidates: dict[tuple[str, str], set[str]] = {}

    for pin in pins:
        lookup = (pin["preview"], pin["type"])
        pinned_candidates.setdefault(lookup, set()).add(pin["key"])

    for item_id, preview in records:
        item_type, display = classify(preview)
        duplicate_pin = item_id in pinned_source_ids
        candidates = pinned_candidates.get((display, item_type), set())
        if not duplicate_pin and candidates:
            decoded = decode_item(cliphist, item_id)
            if decoded is not None:
                duplicate_pin = hashlib.sha256(decoded).hexdigest() in candidates
        if duplicate_pin:
            continue
        items.append({
            "id": item_id,
            "pinKey": "",
            "pinned": False,
            "section": "History",
            "preview": display,
            "type": item_type,
            "search": f"{display} {item_type}".casefold(),
        })

    return emit({"available": True, "items": items, "error": ""})


def restore_item(item_id: str) -> int:
    if not item_id.isdigit() and not item_id.startswith("pin:"):
        return emit({"ok": False, "error": "Invalid clipboard item."})

    wl_copy = shutil.which("wl-copy")
    if not wl_copy:
        return emit({"ok": False, "error": "Clipboard restore is unavailable."})

    try:
        payload = item_payload(item_id)
        if payload is None:
            return emit({"ok": False, "error": "Clipboard item could not be restored."})

        copied = subprocess.run(
            [wl_copy],
            input=payload,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=3.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return emit({"ok": False, "error": "Clipboard item could not be restored."})

    if copied.returncode != 0:
        return emit({"ok": False, "error": "Clipboard item could not be restored."})

    return emit({"ok": True, "error": ""})


def pin_item(item_id: str) -> int:
    if not item_id.isdigit():
        return emit({"ok": False, "error": "Invalid clipboard item."})
    cliphist = shutil.which("cliphist")
    if not cliphist:
        return emit({"ok": False, "error": "Clipboard history is unavailable."})

    payload = decode_item(cliphist, item_id)
    if payload is None:
        return emit({"ok": False, "error": "Clipboard item could not be pinned."})
    key = hashlib.sha256(payload).hexdigest()
    pins = load_pins()
    existing = next((item for item in pins if item["key"] == key), None)
    if existing is not None:
        existing["sourceId"] = item_id
        save_pins(pins)
        return emit({"ok": True, "pinKey": key, "error": ""})
    if len(pins) >= MAX_PINNED_ITEMS:
        return emit({"ok": False, "error": "Pinned clipboard limit reached."})

    available, records = read_cliphist(cliphist)
    raw_preview = next((preview for record_id, preview in records if record_id == item_id), "") \
        if available else ""
    item_type, display = classify(raw_preview)
    ensure_pin_store()
    target = pin_payload_path(key)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{key}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass

    pins.append({
        "key": key,
        "preview": display,
        "type": item_type,
        "sourceId": item_id,
        "pinnedAt": time.time_ns(),
    })
    pins.sort(key=lambda item: (-item["pinnedAt"], item["key"]))
    save_pins(pins)
    return emit({"ok": True, "pinKey": key, "error": ""})


def unpin_item(pin_key: str) -> int:
    if not PIN_KEY_RE.fullmatch(pin_key):
        return emit({"ok": False, "error": "Invalid pinned clipboard item."})
    pins = load_pins()
    remaining = [item for item in pins if item["key"] != pin_key]
    if len(remaining) == len(pins):
        return emit({"ok": False, "error": "Pinned clipboard item was not found."})
    save_pins(remaining)
    try:
        pin_payload_path(pin_key).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return emit({"ok": False, "error": "Pinned clipboard item could not be removed."})
    return emit({"ok": True, "error": ""})


def clear_normal_history() -> int:
    cliphist = shutil.which("cliphist")
    if not cliphist:
        return emit({"ok": False, "error": "Clipboard history is unavailable."})
    try:
        result = subprocess.run(
            [cliphist, "wipe"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=3.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return emit({"ok": False, "error": "Clipboard history could not be cleared."})
    if result.returncode != 0:
        return emit({"ok": False, "error": "Clipboard history could not be cleared."})
    return emit({"ok": True, "error": ""})


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] == "list":
        return list_history()
    if len(argv) == 3 and argv[1] == "select":
        return restore_item(argv[2])
    if len(argv) == 3 and argv[1] == "pin":
        return pin_item(argv[2])
    if len(argv) == 3 and argv[1] == "unpin":
        return unpin_item(argv[2])
    if len(argv) == 2 and argv[1] == "clear":
        return clear_normal_history()
    sys.stderr.write("usage: clipboard.py list | select <id> | pin <id> | unpin <key> | clear\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
