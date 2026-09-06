#!/usr/bin/env python3

"""Compute the source identity embedded into the native Maho Files artifact."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys


SOURCE_FILES = (
    "CMakeLists.txt",
    "source-fingerprint.py",
    "qml/Main.qml",
    "src/main.cpp",
    "src/MahoDirectoryModel.cpp",
    "src/MahoDirectoryModel.h",
    "src/MahoPalette.cpp",
    "src/MahoPalette.h",
    "src/MahoPlacesController.cpp",
    "src/MahoPlacesController.h",
)


def fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in SOURCE_FILES:
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"Maho Files source is missing: {relative}")
        digest.update(relative.encode("utf-8"))
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
