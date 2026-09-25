#!/usr/bin/env python3
"""Small, dependency-light terminal presentation primitives for Maho tools.

This module deliberately contains no health, trust, recovery, or execution
policy.  It only owns bounded text layout, semantic colour, and key decoding.
"""
from __future__ import annotations

import os
import re
import select
import termios
import textwrap
import tty
from typing import Mapping, Sequence, TextIO


ANSI = {
    "reset": "\033[0m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "dim": "\033[2m",
    "reverse": "\033[7m",
}

DEFAULT_SEMANTICS: Mapping[str, str] = {
    "Selection evidence missing": "warn",
    "Evidence not supplied": "warn",
    "None established": "good",
    "Needs approval": "warn",
    "Verified kernel": "good",
    "Verified pair": "good",
    "Trust lost": "bad",
    "CONTAMINATED": "bad",
    "REVALIDATED": "good",
    "REVOKED": "bad",
    "VERIFIED": "good",
    "UNKNOWN": "warn",
    "BLOCKED": "bad",
    "FAIL": "bad",
    "WARN": "warn",
    "PASS": "good",
    "Unresolved": "warn",
    "Possible": "warn",
    "Preserved": "good",
    "Verified": "good",
    "Granted": "good",
    "Success": "good",
    "Missing": "warn",
    "Pending": "warn",
    "Refused": "bad",
    "Failed": "bad",
}


def clip(value: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(value) <= width:
        return value
    if width == 1:
        return "…"
    return value[: width - 1] + "…"


def wrap(value: str, width: int) -> list[str]:
    return textwrap.wrap(
        value, width=max(1, width), replace_whitespace=False,
        drop_whitespace=True, break_long_words=True, break_on_hyphens=False,
    ) or [""]


def short_id(value: str | None, width: int = 28) -> str:
    if value is None:
        return "—"
    if len(value) <= width:
        return value
    if width < 12:
        return clip(value, width)
    side = max(5, width // 2 - 2)
    return value[:side] + "…" + value[-side:]


def human(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").strip()


def status_word(value: str) -> str:
    return {
        "REQUIRED": "Needs approval",
        "GRANTED": "Granted",
        "REFUSED": "Refused",
        "PENDING": "Pending",
        "SUCCESS": "Success",
        "FAILURE": "Failed",
    }.get(value, human(value).capitalize())


def paint(text: str, semantic: str, enabled: bool) -> str:
    if not enabled:
        return text
    color = {
        "good": "green", "warn": "yellow", "bad": "red",
        "dim": "dim", "active": "reverse",
    }.get(semantic)
    if color is None:
        return text
    return ANSI[color] + text + ANSI["reset"]


def colorize_line(text: str, semantics: Mapping[str, str] = DEFAULT_SEMANTICS) -> str:
    pattern = re.compile("|".join(re.escape(item) for item in sorted(semantics, key=len, reverse=True)))
    return pattern.sub(lambda match: paint(match.group(0), semantics[match.group(0)], True), text)


def field_rows(label: str, value: str, width: int) -> list[str]:
    label_width = min(18, max(10, width // 4))
    value_width = max(1, width - label_width - 3)
    wrapped = wrap(value, value_width)
    rows = [f"{label:<{label_width}} : {wrapped[0]}"]
    rows.extend(" " * (label_width + 3) + part for part in wrapped[1:])
    return rows


def box(title: str, rows: Sequence[str], width: int) -> list[str]:
    width = max(16, width)
    inner = width - 2
    heading = f" {title} "
    out = ["┌" + heading + "─" * max(0, inner - len(heading)) + "┐"]
    for row in rows:
        for part in wrap(row, inner - 2):
            out.append("│ " + clip(part, inner - 2).ljust(inner - 2) + " │")
    out.append("└" + "─" * inner + "┘")
    return out


def columns(left: Sequence[str], right: Sequence[str], width: int, gap: int = 2) -> list[str]:
    left_width = (width - gap) // 2
    right_width = width - gap - left_width
    height = max(len(left), len(right))
    out = []
    for index in range(height):
        l = left[index] if index < len(left) else ""
        r = right[index] if index < len(right) else ""
        out.append(clip(l, left_width).ljust(left_width) + " " * gap + clip(r, right_width))
    return out


def bounded_lines(lines: Sequence[str], height: int, width: int, more: str = "… more") -> list[str]:
    available = max(1, height)
    result = [clip(line, width) for line in lines[:available]]
    if len(lines) > available:
        result[-1] = clip(more, width)
    return result


def decode_escape_sequence(raw: bytes) -> str:
    """Decode one complete terminal escape sequence into a semantic key."""
    exact = {
        b"\x1b[A": "up", b"\x1b[B": "down", b"\x1b[C": "right",
        b"\x1b[D": "left", b"\x1bOA": "up", b"\x1bOB": "down",
        b"\x1bOC": "right", b"\x1bOD": "left",
        b"\x1b[Z": "shift-tab",
        b"\x1b[5~": "page-up", b"\x1b[6~": "page-down",
        b"\x1b[H": "home", b"\x1b[1~": "home", b"\x1bOH": "home",
        b"\x1b[F": "end", b"\x1b[4~": "end", b"\x1bOF": "end",
    }
    if raw in exact:
        return exact[raw]
    if raw.startswith(b"\x1b[") and raw[-1:] in {b"A", b"B", b"C", b"D"}:
        return {b"A": "up", b"B": "down", b"C": "right", b"D": "left"}[raw[-1:]]
    if raw.startswith(b"\x1b[<") and raw[-1:] in {b"M", b"m"}:
        try:
            button, x, y = (int(value) for value in raw[3:-1].decode("ascii").split(";"))
        except (UnicodeDecodeError, ValueError):
            return "unknown"
        if button & 64:
            return f"mouse-wheel-{'down' if button & 1 else 'up'}:{x}:{y}"
        if raw[-1:] == b"M" and button & 3 == 0:
            return f"mouse-left:{x}:{y}"
        return "mouse"
    if raw == b"\x1b":
        return "escape"
    return "unknown"


def read_key(stdin: TextIO, timeout: float | None = None) -> str:
    """Read one navigation key; raw mode is used only for a real TTY."""
    is_tty = bool(getattr(stdin, "isatty", lambda: False)())
    if not is_tty:
        value = stdin.readline()
        return value.strip().lower() if value else "q"
    fd = stdin.fileno()
    previous = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        if timeout is not None:
            ready, _, _ = select.select([fd], [], [], timeout)
            if not ready:
                return "timeout"
        first = os.read(fd, 1)
        if not first:
            return "q"
        if first == b"\x1b":
            sequence = bytearray(first)
            while len(sequence) < 64:
                ready, _, _ = select.select([fd], [], [], 0.01)
                if not ready:
                    break
                sequence.extend(os.read(fd, 1))
                if len(sequence) >= 3 and 0x40 <= sequence[-1] <= 0x7e:
                    break
            return decode_escape_sequence(bytes(sequence))
        if first == b"\t":
            return "tab"
        if first in {b"\r", b"\n"}:
            return "enter"
        if first == b"\x03":
            return "q"
        return first.decode("utf-8", errors="ignore").lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)
