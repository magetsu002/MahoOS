#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_update_normal_host import NormalProductionOps


def field(path: Path, key: str) -> str | None:
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    marker = f"%{key}%"
    for index, line in enumerate(lines[:-1]):
        if line == marker:
            return lines[index + 1]
    return None


def main() -> None:
    pacman = Path("/usr/bin/pacman")
    local = Path("/var/lib/pacman/local")
    if not pacman.is_file() or not local.is_dir():
        print("SKIP real rooted Pacman integration unavailable on this runner")
        return

    candidates = ("github-cli", "bash")
    package = None
    for name in candidates:
        result = subprocess.run(
            [str(pacman), "--query", "--", name],
            text=True, capture_output=True, check=False,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
        if result.returncode == 0:
            package = name
            break
    if package is None:
        print("SKIP no integration package is installed")
        return

    package_dir = None
    for directory in local.iterdir():
        desc = directory / "desc"
        if directory.is_dir() and desc.is_file() and field(desc, "NAME") == package:
            package_dir = directory
            break
    if package_dir is None:
        raise AssertionError(f"cannot locate local Pacman DB entry for {package}")

    with tempfile.TemporaryDirectory(prefix="maho-real-rooted-pacman-") as temporary:
        candidate_root = Path(temporary) / "candidate"
        candidate_db = candidate_root / "var/lib/pacman/local"
        candidate_db.mkdir(parents=True)
        shutil.copy2(local / "ALPM_DB_VERSION", candidate_db / "ALPM_DB_VERSION")
        shutil.copytree(package_dir, candidate_db / package_dir.name)

        ops = object.__new__(NormalProductionOps)
        ops.expected = {package: "integration"}
        live = ops._live_package_paths_by_name()[package]
        rooted = ops._package_paths(candidate_root, package)

        if live != rooted:
            live_only = sorted(set(live) - set(rooted))[:20]
            rooted_only = sorted(set(rooted) - set(live))[:20]
            raise AssertionError(
                f"rooted Pacman canonicalization differs: live_only={live_only} rooted_only={rooted_only}"
            )

        raw = subprocess.run(
            [
                str(pacman), "--root", str(candidate_root),
                "--query", "--list", "--", package,
            ],
            text=True, capture_output=True, check=True,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        ).stdout
        first = next(
            line.partition(" ")[2]
            for line in raw.splitlines()
            if line.startswith(package + " ")
        )
        if not first.startswith(str(candidate_root) + "/"):
            raise AssertionError("real Pacman rooted output did not contain candidate-root prefix")

        print(
            f"PASS real Pacman --root path semantics canonicalize exactly "
            f"({package}, {len(live)} paths)"
        )

    try:
        NormalProductionOps._canonical_rooted_package_path(
            Path("/candidate"), "/etc/passwd"
        )
    except RuntimeError:
        print("PASS rooted package path escaping candidate fails closed")
    else:
        raise AssertionError("candidate-root escape unexpectedly canonicalized")


if __name__ == "__main__":
    main()
