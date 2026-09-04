#!/usr/bin/env python3

"""Presentation adapter for the existing cliphist clipboard history.

This module intentionally does not store, watch, or log clipboard contents.
It only reads the existing history and restores a selected item with wl-copy.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
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


def list_history() -> int:
    cliphist = shutil.which("cliphist")
    if not cliphist:
        return emit({
            "available": False,
            "items": [],
            "error": "Clipboard history is unavailable.",
        })

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
        return emit({
            "available": False,
            "items": [],
            "error": "Clipboard history could not be read.",
        })

    if result.returncode != 0:
        return emit({
            "available": False,
            "items": [],
            "error": "Clipboard history could not be read.",
        })

    items: list[dict[str, str]] = []
    for item_id, preview in parse_history_records(result.stdout):
        item_type, display = classify(preview)
        items.append({
            "id": item_id,
            "preview": display,
            "type": item_type,
            "search": f"{display} {item_type}".casefold(),
        })

    return emit({"available": True, "items": items, "error": ""})


def restore_item(item_id: str) -> int:
    if not item_id.isdigit():
        return emit({"ok": False, "error": "Invalid clipboard item."})

    cliphist = shutil.which("cliphist")
    wl_copy = shutil.which("wl-copy")
    if not cliphist or not wl_copy:
        return emit({"ok": False, "error": "Clipboard restore is unavailable."})

    try:
        decoded = subprocess.run(
            [cliphist, "decode", item_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=3.0,
        )
        if decoded.returncode != 0:
            return emit({"ok": False, "error": "Clipboard item could not be restored."})

        copied = subprocess.run(
            [wl_copy],
            input=decoded.stdout,
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


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] == "list":
        return list_history()
    if len(argv) == 3 and argv[1] == "select":
        return restore_item(argv[2])
    sys.stderr.write("usage: clipboard.py list | select <id>\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
