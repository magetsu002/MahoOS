#!/usr/bin/env python3
"""Concrete production host operations for normal-impact Maho Update."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

from guardian_admission import AdmissionOutcome
from guardian_native_admission import CandidateRoots, root_identity
from maho_update_admission import evaluate_normal_production_candidate, guardian_transaction_id
from maho_update_native import NativeBtrfsOps
from maho_update_normal import NormalExecutionPlan
from maho_update_state import validate_transaction


class NormalProductionOps:
    fixture_safe = False
    production_safe = True
    PACMAN = "/usr/bin/pacman"

    def __init__(
        self, *,
        transaction: Mapping[str, Any],
        cache_root: str | os.PathLike[str],
        btrfs: NativeBtrfsOps,
        candidate: Mapping[str, Any],
    ) -> None:
        self.transaction = validate_transaction(transaction)
        self.cache = Path(cache_root).resolve(strict=True)
        self.btrfs = btrfs
        self.candidate = dict(candidate)
        self.expected = {
            item["name"]: item["candidate_version"]
            for item in self.transaction["package_generation"]["packages"]
        }
        self.previous = {
            item["name"]: item["installed_version"]
            for item in self.transaction["package_generation"]["packages"]
        }
        self.admission = None
        self.roots: CandidateRoots | None = None
        self.live_mutation_started = False
        self.last_verification: dict[str, Any] | None = None

    @staticmethod
    def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(command), text=True, capture_output=True, check=False,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )

    def _payloads(self, plan: NormalExecutionPlan) -> tuple[str, ...]:
        values = tuple(str(Path(item).resolve(strict=True)) for item in plan.payload_paths)
        if not values or any(Path(item).parent != self.cache for item in values):
            raise ValueError("normal payload escapes certified staging cache")
        return values

    def _query_versions(self, *, root: Path | None = None) -> dict[str, str]:
        names = tuple(sorted(self.expected))
        if root is None:
            command = (self.PACMAN, "--query", "--", *names)
        else:
            command = (
                self.PACMAN, "--root", str(root), "--dbpath", str(root / "var/lib/pacman"),
                "--query", "--", *names,
            )
        result = self._run(command)
        if result.returncode != 0:
            raise RuntimeError("normal package version query failed: " + result.stderr.strip())
        observed: dict[str, str] = {}
        for line in result.stdout.splitlines():
            name, sep, version = line.partition(" ")
            if sep:
                observed[name] = version.strip()
        return observed

    def install_candidate(self, plan: NormalExecutionPlan) -> Mapping[str, Any]:
        root = self.btrfs.offline_root
        config = root / "etc/maho/pacman.conf"
        if config.is_symlink() or not config.is_file():
            return {"ok": False, "reason": "candidate canonical Pacman authority missing"}
        command = (
            self.PACMAN, "--sysroot", str(root), "--config", "/etc/maho/pacman.conf",
            "--upgrade", "--noconfirm", "--needed", "--", *self._payloads(plan),
        )
        result = self._run(command)
        if result.returncode != 0:
            return {"ok": False, "exit_code": result.returncode, "stderr": result.stderr[-4000:]}
        observed = self._query_versions(root=root)
        return {"ok": observed == self.expected, "observed": observed, "expected": self.expected}

    def guardian_admit(self, plan: NormalExecutionPlan) -> Mapping[str, Any]:
        self.btrfs.freeze_normal_candidate(str(self.candidate["uuid"]))
        paths = self.btrfs.admission_roots(str(self.candidate["uuid"]), str(self.candidate["admission_base_uuid"]))
        roots = CandidateRoots.create(
            transaction_id=guardian_transaction_id(plan.transaction_id),
            candidate_id=str(self.candidate["uuid"]),
            base_root=paths["base_root"],
            candidate_root=paths["candidate_root"],
        )
        result = evaluate_normal_production_candidate(roots, self.transaction)
        self.admission = result
        self.roots = roots
        return {
            "ok": result.decision.outcome is AdmissionOutcome.ALLOW,
            "outcome": result.decision.outcome.value,
            "reasons": list(result.decision.reasons),
            "graph_id": str(result.inspection.graph.graph_id),
            "base_root_identity": result.inspection.base_root_identity,
            "candidate_root_identity": result.inspection.candidate_root_identity,
            "promotion_authority": result.promotion_authority.as_dict() if result.promotion_authority else None,
        }

    def _live_package_paths(self) -> set[str]:
        result = self._run((self.PACMAN, "--query", "--list", "--", *sorted(self.expected)))
        if result.returncode != 0:
            raise RuntimeError("cannot enumerate live target package paths")
        paths: set[str] = set()
        for line in result.stdout.splitlines():
            _, sep, value = line.partition(" ")
            if sep and value.startswith("/"):
                paths.add(value.rstrip("/"))
        return paths

    def _active_target_processes(self) -> list[int]:
        target_paths = self._live_package_paths()
        active: list[int] = []
        proc = Path("/proc")
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            observed: set[str] = set()
            try:
                observed.add(os.readlink(entry / "exe"))
            except OSError:
                pass
            try:
                raw = (entry / "cmdline").read_bytes()
                observed.update(part.decode(errors="ignore") for part in raw.split(b"\0") if part.startswith(b"/"))
            except OSError:
                pass
            try:
                for line in (entry / "maps").read_text(errors="ignore").splitlines():
                    fields = line.split(maxsplit=5)
                    if len(fields) == 6 and fields[5].startswith("/"):
                        observed.add(fields[5])
            except OSError:
                pass
            if target_paths.intersection(observed):
                active.append(pid)
        return sorted(active)

    def activate(self, plan: NormalExecutionPlan) -> Mapping[str, Any]:
        if self.admission is None or self.admission.decision.outcome is not AdmissionOutcome.ALLOW:
            return {"ok": False, "reason": "Guardian did not authorize normal activation"}
        if Path("/var/lib/pacman/db.lck").exists():
            return {"ok": False, "reason": "live Pacman lock exists"}
        active = self._active_target_processes()
        if active:
            return {"ok": False, "reason": "target package is active in running processes", "pids": active}
        identity = self.btrfs.root_identity()
        if identity.subvolume_uuid != self.candidate.get("parent_root_uuid"):
            return {"ok": False, "reason": "live root identity drifted since candidate creation"}
        before = self._query_versions()
        if before != self.previous:
            return {"ok": False, "reason": "live package versions drifted", "observed": before, "expected": self.previous}
        self.live_mutation_started = True
        result = self._run((
            self.PACMAN, "--config", "/etc/maho/pacman.conf",
            "--upgrade", "--noconfirm", "--needed", "--", *self._payloads(plan),
        ))
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout_tail": result.stdout[-4000:],
            "stderr_tail": result.stderr[-4000:],
        }

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _package_paths(self, root: Path, name: str) -> tuple[str, ...]:
        result = self._run((
            self.PACMAN, "--root", str(root), "--dbpath", str(root / "var/lib/pacman"),
            "--query", "--list", "--", name,
        ))
        if result.returncode != 0:
            raise RuntimeError(f"cannot enumerate certified package paths:{name}")
        paths: list[str] = []
        for line in result.stdout.splitlines():
            observed, sep, value = line.partition(" ")
            if sep and observed == name and value.startswith("/"):
                paths.append(value)
        if not paths:
            raise RuntimeError(f"certified package path set empty:{name}")
        return tuple(sorted(set(paths)))

    def _compare_path(self, candidate_root: Path, relative: str) -> bool:
        rel = relative.lstrip("/")
        expected = candidate_root / rel
        actual = Path("/") / rel
        if expected.is_symlink() or actual.is_symlink():
            return expected.is_symlink() and actual.is_symlink() and os.readlink(expected) == os.readlink(actual)
        if expected.is_dir() or actual.is_dir():
            return expected.is_dir() and actual.is_dir() and (expected.stat().st_mode & 0o7777) == (actual.stat().st_mode & 0o7777)
        if not expected.is_file() or not actual.is_file():
            return False
        return (
            (expected.stat().st_mode & 0o7777) == (actual.stat().st_mode & 0o7777)
            and expected.stat().st_size == actual.stat().st_size
            and self._hash(expected) == self._hash(actual)
        )

    def verify(self, plan: NormalExecutionPlan) -> Mapping[str, Any]:
        if self.roots is None or self.admission is None:
            return {"ok": False, "reason": "normal admission evidence missing"}
        observed = self._query_versions()
        if observed != self.expected:
            return {"ok": False, "reason": "live package version verification failed", "observed": observed, "expected": self.expected}
        candidate_root = self.roots.candidate_root
        mismatches: list[str] = []
        checked = 0
        for name in sorted(self.expected):
            for path in self._package_paths(candidate_root, name):
                checked += 1
                if not self._compare_path(candidate_root, path):
                    mismatches.append(path)
                    if len(mismatches) >= 32:
                        break
            if mismatches:
                break
        result = {
            "ok": not mismatches,
            "observed": observed,
            "expected": self.expected,
            "package_paths_checked": checked,
            "mismatches": mismatches,
            "graph_id": str(self.admission.inspection.graph.graph_id),
            "base_root_identity": self.admission.inspection.base_root_identity,
            "candidate_root_identity": self.admission.inspection.candidate_root_identity,
        }
        self.last_verification = result
        return result

    def cleanup_success(self) -> Mapping[str, Any]:
        return self.btrfs.cleanup_candidate(str(self.candidate["uuid"]))
