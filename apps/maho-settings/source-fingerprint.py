#!/usr/bin/env python3
"""Compute the source identity embedded into the native Maho Settings artifact."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys

ALLOWED_SUFFIXES = {".cpp", ".h", ".qml", ".desktop", ".py"}
ALLOWED_NAMES = {"CMakeLists.txt"}


def source_files(root: Path) -> list[Path]:
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if "prebuilt" in relative.parts or "__pycache__" in relative.parts:
            continue
        if path.name in ALLOWED_NAMES or path.suffix in ALLOWED_SUFFIXES:
            files.append(relative)
    return sorted(files, key=lambda item: item.as_posix())


def fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    files = source_files(root)
    if not files:
        raise FileNotFoundError("Maho Settings source tree is empty")
    for relative in files:
        path = root / relative
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else Path(__file__).resolve().parent
    if len(sys.argv) > 2:
        print("usage: source-fingerprint.py [SOURCE_ROOT]", file=sys.stderr)
        return 2
    try:
        print(fingerprint(root))
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
