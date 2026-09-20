#!/usr/bin/env python3
"""Concrete production host operations for normal-impact Maho Update."""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from pathlib import Path
import stat
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
    PACMAN_CONF = "/usr/bin/pacman-conf"
    PACMAN_LOCK = Path("/var/lib/pacman/db.lck")
    SYSTEM_HOOK_DIR = Path("/usr/share/libalpm/hooks")
    CUSTOM_HOOK_DIR = Path("/etc/pacman.d/hooks")
    MASKED_HOST_HOOKS = (
        "05-snap-pac-pre.hook",
        "10-limine-snapper-lock.hook",
        "zz-snap-pac-post.hook",
    )
    ALLOWED_HOOK_IDENTITIES = {
        "35-systemd-update.hook": {
            "hook_sha256": "1090b7b1edba2042298b609a77bbe122982ca936208408fb79d77b33a2f3c27a",
            "script": "/usr/share/libalpm/scripts/systemd-hook",
            "script_sha256": "90e00dd01359565be85a8cdd93b424b4c1c89563300d16eaf0e7eedc349bf9fc",
        },
    }
    MAX_GUARDIAN_INSPECTION_ERRORS = 128

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
                self.PACMAN, "--root", str(root),
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

    def _payload_scriptlet_free(self, path: str) -> tuple[bool, str | None]:
        result = self._run((self.PACMAN, "--query", "--file", "--info", "--", path))
        if result.returncode != 0:
            return False, "package metadata inspection failed"
        value = None
        for line in result.stdout.splitlines():
            key, sep, raw = line.partition(":")
            if sep and key.strip() == "Install Script":
                value = raw.strip()
                break
        if value is None:
            return False, "package install-script metadata is missing"
        if value != "No":
            return False, "package install script is outside certified normal profile"
        return True, None

    @staticmethod
    def _target_matches(patterns: Sequence[str], subject: str) -> bool:
        matched = False
        for raw in patterns:
            inverted = raw.startswith("!")
            pattern = raw[1:] if inverted else raw
            if pattern and fnmatch.fnmatchcase(subject, pattern):
                matched = not inverted
        return matched

    @classmethod
    def _parse_hook(cls, path: Path) -> tuple[dict[str, Any], ...]:
        triggers: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for raw in path.read_text(encoding="utf-8", errors="strict").splitlines():
            line = raw.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line == "[Trigger]":
                current = {"operations": [], "type": None, "targets": []}
                triggers.append(current)
                continue
            if line.startswith("[") and line.endswith("]"):
                current = None
                continue
            if current is None:
                continue
            key, sep, value = line.partition("=")
            if not sep:
                continue
            key, value = key.strip(), value.strip()
            if key == "Operation":
                current["operations"].append(value)
            elif key == "Type":
                current["type"] = "Path" if value == "File" else value
            elif key == "Target":
                current["targets"].append(value)
        if not triggers:
            raise ValueError(f"ALPM hook has no trigger:{path.name}")
        for trigger in triggers:
            if not trigger["operations"] or trigger["type"] not in {"Path", "Package"} or not trigger["targets"]:
                raise ValueError(f"ALPM hook trigger is incomplete:{path.name}")
        return tuple(triggers)

    @classmethod
    def _effective_hook_files(cls, system_dir: Path, custom_dir: Path) -> dict[str, Path]:
        effective: dict[str, Path] = {}
        for directory in (system_dir, custom_dir):
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.hook")):
                if path.is_symlink() and os.readlink(path) == "/dev/null":
                    effective.pop(path.name, None)
                elif path.is_file():
                    effective[path.name] = path
        for name in cls.MASKED_HOST_HOOKS:
            effective.pop(name, None)
        return effective

    def _payload_path_sets(self, payloads: Sequence[str]) -> dict[str, tuple[str, ...]]:
        rows: dict[str, set[str]] = {}
        for payload in payloads:
            identity = self._run((self.PACMAN, "--query", "--file", "--", payload))
            if identity.returncode != 0:
                raise RuntimeError("cannot identify exact payload during normal preflight")
            name, sep, _version = identity.stdout.strip().partition(" ")
            if not sep or name not in self.expected or name in rows:
                raise RuntimeError("exact payload identity is outside bounded normal generation")
            listing = self._run((self.PACMAN, "--query", "--file", "--list", "--", payload))
            if listing.returncode != 0:
                raise RuntimeError("cannot enumerate exact payload paths for normal preflight")
            paths: set[str] = set()
            for line in listing.stdout.splitlines():
                observed, path_sep, value = line.partition(" ")
                if path_sep and observed == name and value.startswith("/"):
                    paths.add(value.rstrip("/"))
            if not paths:
                raise RuntimeError(f"exact payload path set is empty:{name}")
            rows[name] = paths
        if set(rows) != set(self.expected):
            raise RuntimeError("exact payload set does not cover bounded normal generation")
        return {name: tuple(sorted(paths)) for name, paths in rows.items()}

    def _payload_file_paths(self, payloads: Sequence[str]) -> tuple[str, ...]:
        paths: set[str] = set()
        for payload in payloads:
            listing = self._run((self.PACMAN, "--query", "--file", "--list", "--", payload))
            if listing.returncode != 0:
                raise RuntimeError("cannot enumerate exact archive paths for hook preflight")
            for line in listing.stdout.splitlines():
                _, sep, value = line.partition(" ")
                if sep and value.startswith("/"):
                    paths.add(value.lstrip("/"))
        if not paths:
            raise RuntimeError("exact archive path set is empty during hook preflight")
        return tuple(sorted(paths))

    def _in_place_upgrade_profile(self, payloads: Sequence[str]) -> dict[str, Any]:
        live = self._live_package_paths_by_name()
        exact = self._payload_path_sets(payloads)
        stable = live == exact
        material = json.dumps(exact, sort_keys=True, separators=(",", ":")).encode()
        return {
            "ok": stable,
            "profile": "in-place-static-package-path-set-v1",
            "path_set_sha256": hashlib.sha256(material).hexdigest(),
            "installed": {name: len(paths) for name, paths in live.items()},
            "artifact": {name: len(paths) for name, paths in exact.items()},
        }

    @classmethod
    def _triggered_hook_names(
        cls, *, package_names: Sequence[str], archive_paths: Sequence[str],
        system_dir: Path, custom_dir: Path,
    ) -> tuple[str, ...]:
        packages = tuple(sorted(set(package_names)))
        paths = tuple(sorted(set(archive_paths)))
        triggered: list[str] = []
        for name, hook in sorted(cls._effective_hook_files(system_dir, custom_dir).items()):
            for trigger in cls._parse_hook(hook):
                if "Upgrade" not in trigger["operations"]:
                    continue
                subjects = packages if trigger["type"] == "Package" else paths
                if any(cls._target_matches(trigger["targets"], subject) for subject in subjects):
                    triggered.append(name)
                    break
        return tuple(triggered)

    def _hook_profile(self, payloads: Sequence[str]) -> dict[str, Any]:
        result = self._run((self.PACMAN_CONF, "--config", "/etc/maho/pacman.conf", "HookDir"))
        hookdirs = tuple(line.strip().rstrip("/") for line in result.stdout.splitlines() if line.strip()) if result.returncode == 0 else ()
        expected_custom = str(self.CUSTOM_HOOK_DIR)
        if hookdirs != (expected_custom,):
            return {"ok": False, "reason": "canonical Pacman HookDir authority drifted", "hookdirs": list(hookdirs)}
        archive_paths = self._payload_file_paths(payloads)
        try:
            effective = self._effective_hook_files(self.SYSTEM_HOOK_DIR, self.CUSTOM_HOOK_DIR)
            triggered = self._triggered_hook_names(
                package_names=tuple(sorted(self.expected)), archive_paths=archive_paths,
                system_dir=self.SYSTEM_HOOK_DIR, custom_dir=self.CUSTOM_HOOK_DIR,
            )
        except (OSError, UnicodeError, ValueError) as exc:
            return {"ok": False, "reason": f"ALPM hook policy unreadable:{exc}"}
        disallowed = tuple(name for name in triggered if name not in self.ALLOWED_HOOK_IDENTITIES)
        allowed: list[str] = []
        identity_rows: list[dict[str, str]] = []
        for name in triggered:
            expected = self.ALLOWED_HOOK_IDENTITIES.get(name)
            if expected is None:
                continue
            hook_path = effective.get(name)
            script_path = Path(expected["script"])
            if hook_path is None or not script_path.is_file():
                return {"ok": False, "reason": f"certified benign ALPM hook is unavailable:{name}"}
            if self._hash(hook_path) != expected["hook_sha256"] or self._hash(script_path) != expected["script_sha256"]:
                return {"ok": False, "reason": f"certified benign ALPM hook identity drifted:{name}"}
            allowed.append(name)
            identity_rows.append({
                "name": name,
                "hook_sha256": expected["hook_sha256"],
                "script_sha256": expected["script_sha256"],
            })
        identity_sha256 = hashlib.sha256(
            json.dumps(identity_rows, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return {
            "ok": not disallowed,
            "profile": "bounded-hooks-static-path-set-v1",
            "triggered_hooks": list(triggered),
            "allowed_hooks": allowed,
            "disallowed_hooks": list(disallowed),
            "masked_hooks": list(self.MASKED_HOST_HOOKS),
            "allowed_hook_identity_sha256": identity_sha256,
            "payload_path_count": len(archive_paths),
        }

    @classmethod
    def _create_hook_overrides(cls, directory: Path) -> tuple[Path, ...]:
        directory.mkdir(mode=0o755, parents=True, exist_ok=True)
        created: list[Path] = []
        for name in cls.MASKED_HOST_HOOKS:
            path = directory / name
            if path.exists() or path.is_symlink():
                if path.is_symlink() and os.readlink(path) == "/dev/null":
                    continue
                raise RuntimeError(f"normal hook override conflicts with existing policy:{name}")
            path.symlink_to("/dev/null")
            created.append(path)
        return tuple(created)

    @staticmethod
    def _remove_hook_overrides(created: Sequence[Path], directory: Path) -> None:
        for path in reversed(tuple(created)):
            try: path.unlink()
            except FileNotFoundError: pass
        try: directory.rmdir()
        except OSError: pass

    def install_candidate(self, plan: NormalExecutionPlan) -> Mapping[str, Any]:
        root = self.btrfs.offline_root
        config = root / "etc/maho/pacman.conf"
        if config.is_symlink() or not config.is_file():
            return {"ok": False, "reason": "candidate canonical Pacman authority missing"}
        payloads = self._payloads(plan)
        for payload in payloads:
            ok, reason = self._payload_scriptlet_free(payload)
            if not ok:
                return {"ok": False, "reason": reason, "payload": payload}
        in_place = self._in_place_upgrade_profile(payloads)
        if in_place.get("ok") is not True:
            return {"ok": False, "reason": "exact package is not an in-place static-path upgrade", "in_place_profile": in_place}
        hook_profile = self._hook_profile(payloads)
        if hook_profile.get("ok") is not True:
            return {"ok": False, "reason": "exact package triggers hooks outside certified normal profile", "hook_profile": hook_profile}
        hooks = root / "etc/pacman.d/hooks"
        created: tuple[Path, ...] = ()
        runtime = None
        try:
            runtime = self.btrfs.mount_normal_candidate_runtime()
            created = self._create_hook_overrides(hooks)
            command = (
                self.PACMAN, "--sysroot", str(root), "--config", "/etc/maho/pacman.conf",
                "--upgrade", "--noconfirm", "--needed", "--noscriptlet", "--", *payloads,
            )
            result = self._run(command)
            if result.returncode != 0:
                return {
                    "ok": False,
                    "exit_code": result.returncode,
                    "stdout_tail": result.stdout[-4000:],
                    "stderr_tail": result.stderr[-4000:],
                    "runtime": runtime,
                }
        finally:
            self._remove_hook_overrides(created, hooks)
            self.btrfs.unmount_normal_candidate_runtime()
        observed = self._query_versions(root=root)
        path_set = self._path_set_evidence(root)
        return {
            "ok": observed == self.expected and path_set["ok"] is True,
            "observed": observed,
            "expected": self.expected,
            "runtime": runtime,
            "path_set": path_set,
            "in_place_profile": in_place,
            "hook_profile": hook_profile,
        }

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
        return self._guardian_evidence(result)

    @classmethod
    def _guardian_evidence(cls, result: Any) -> dict[str, Any]:
        errors = tuple(result.inspection.errors)
        bounded_errors = errors[:cls.MAX_GUARDIAN_INSPECTION_ERRORS]
        effects = tuple(result.inspection.graph.effects)
        effects_by_kind: dict[str, int] = {}
        effects_by_operation: dict[str, int] = {}
        for effect in effects:
            kind = effect.kind.value
            effects_by_kind[kind] = effects_by_kind.get(kind, 0) + 1
            effects_by_operation[effect.operation] = effects_by_operation.get(effect.operation, 0) + 1
        return {
            "ok": result.decision.outcome is AdmissionOutcome.ALLOW,
            "outcome": result.decision.outcome.value,
            "reasons": list(result.decision.reasons),
            "graph_id": str(result.inspection.graph.graph_id),
            "base_root_identity": result.inspection.base_root_identity,
            "candidate_root_identity": result.inspection.candidate_root_identity,
            "inspection_errors": list(bounded_errors),
            "inspection_errors_total": len(errors),
            "inspection_errors_truncated": len(errors) > len(bounded_errors),
            "inspection_errors_sha256": hashlib.sha256(
                json.dumps(errors, ensure_ascii=False, separators=(",", ":")).encode()
            ).hexdigest(),
            "inspection_complete": result.inspection.graph.inspection_complete,
            "runtime_complete": result.inspection.runtime_complete,
            "runtime_isolated": result.inspection.runtime_isolated,
            "effects": {
                "total": len(effects),
                "declared": sum(1 for effect in effects if effect.declared),
                "undeclared": sum(1 for effect in effects if not effect.declared),
                "by_kind": dict(sorted(effects_by_kind.items())),
                "by_operation": dict(sorted(effects_by_operation.items())),
            },
            "promotion_authority": result.promotion_authority.as_dict() if result.promotion_authority else None,
        }

    def _live_package_paths_by_name(self) -> dict[str, tuple[str, ...]]:
        result = self._run((self.PACMAN, "--query", "--list", "--", *sorted(self.expected)))
        if result.returncode != 0:
            raise RuntimeError("cannot enumerate live target package paths")
        rows: dict[str, set[str]] = {name: set() for name in self.expected}
        for line in result.stdout.splitlines():
            name, sep, value = line.partition(" ")
            if sep and name in rows and value.startswith("/"):
                rows[name].add(value.rstrip("/"))
        if any(not values for values in rows.values()):
            raise RuntimeError("live target package path set is incomplete")
        return {name: tuple(sorted(values)) for name, values in rows.items()}

    def _live_package_paths(self) -> set[str]:
        return {path for values in self._live_package_paths_by_name().values() for path in values}

    def _candidate_package_paths_by_name(self, root: Path) -> dict[str, tuple[str, ...]]:
        return {name: self._package_paths(root, name) for name in sorted(self.expected)}

    def _path_set_evidence(self, candidate_root: Path) -> dict[str, Any]:
        live = self._live_package_paths_by_name()
        candidate = self._candidate_package_paths_by_name(candidate_root)
        stable = live == candidate
        material = json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode()
        return {
            "ok": stable,
            "profile": "ordinary-files-static-path-set-v1",
            "path_set_sha256": hashlib.sha256(material).hexdigest(),
            "live": {name: len(paths) for name, paths in live.items()},
            "candidate": {name: len(paths) for name, paths in candidate.items()},
        }

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

    def preflight_activation(self, plan: NormalExecutionPlan) -> Mapping[str, Any]:
        if self.admission is None or self.admission.decision.outcome is not AdmissionOutcome.ALLOW:
            return {"ok": False, "reason": "Guardian did not authorize normal activation"}
        if self.PACMAN_LOCK.exists():
            return {"ok": False, "reason": "live Pacman lock exists"}
        path_set = self._path_set_evidence(self.roots.candidate_root) if self.roots is not None else {"ok": False}
        if path_set.get("ok") is not True:
            return {"ok": False, "reason": "package path set exceeds certified normal profile", "path_set": path_set}
        active = self._active_target_processes()
        if active:
            return {"ok": False, "reason": "target package is active in running processes", "pids": active}
        identity = self.btrfs.root_identity()
        if identity.subvolume_uuid != self.candidate.get("parent_root_uuid"):
            return {"ok": False, "reason": "live root identity drifted since candidate creation"}
        before = self._query_versions()
        if before != self.previous:
            return {"ok": False, "reason": "live package versions drifted", "observed": before, "expected": self.previous}
        payloads = self._payloads(plan)
        for payload in payloads:
            ok, reason = self._payload_scriptlet_free(payload)
            if not ok:
                return {"ok": False, "reason": reason, "payload": payload}
        in_place = self._in_place_upgrade_profile(payloads)
        if in_place.get("ok") is not True:
            return {"ok": False, "reason": "in-place package profile drifted before live activation", "in_place_profile": in_place}
        hook_profile = self._hook_profile(payloads)
        if hook_profile.get("ok") is not True:
            return {"ok": False, "reason": "ALPM hook policy drifted before live activation", "hook_profile": hook_profile}
        return {
            "ok": True,
            "path_set": path_set,
            "active_pids": [],
            "root_identity": {
                "filesystem_uuid": identity.filesystem_uuid,
                "fsroot": identity.fsroot,
                "source": identity.source,
                "device": identity.device,
                "subvolume_uuid": identity.subvolume_uuid,
            },
            "observed_previous_versions": before,
            "expected_previous_versions": self.previous,
            "in_place_profile": in_place,
            "hook_profile": hook_profile,
        }

    def activate(self, plan: NormalExecutionPlan) -> Mapping[str, Any]:
        preflight = self.preflight_activation(plan)
        if preflight.get("ok") is not True:
            return preflight
        payloads = self._payloads(plan)
        in_place = preflight["in_place_profile"]
        hook_profile = preflight["hook_profile"]
        hookdir = self.btrfs.run_root / "normal-live-hooks"
        created: tuple[Path, ...] = ()
        try:
            created = self._create_hook_overrides(hookdir)
            self.live_mutation_started = True
            result = self._run((
                self.PACMAN, "--config", "/etc/maho/pacman.conf", "--hookdir", str(hookdir),
                "--upgrade", "--noconfirm", "--needed", "--noscriptlet", "--", *payloads,
            ))
        finally:
            self._remove_hook_overrides(created, hookdir)
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout_tail": result.stdout[-4000:],
            "stderr_tail": result.stderr[-4000:],
            "masked_host_hooks": list(self.MASKED_HOST_HOOKS),
            "in_place_profile": in_place,
            "hook_profile": hook_profile,
        }

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _canonical_rooted_package_path(root: Path, value: str) -> str:
        root_text = os.path.normpath(os.path.abspath(str(root)))
        path_text = os.path.normpath(value)
        if not os.path.isabs(path_text):
            raise RuntimeError("rooted Pacman package path is not absolute")
        try:
            common = os.path.commonpath((root_text, path_text))
        except ValueError as exc:
            raise RuntimeError("rooted Pacman package path cannot be bounded to candidate root") from exc
        if common != root_text:
            raise RuntimeError("rooted Pacman package path escaped candidate root")
        relative = os.path.relpath(path_text, root_text)
        if relative == ".":
            return "/"
        if relative == ".." or relative.startswith("../"):
            raise RuntimeError("rooted Pacman package path escaped candidate root")
        return "/" + relative.replace(os.sep, "/").rstrip("/")

    def _package_paths(self, root: Path, name: str) -> tuple[str, ...]:
        result = self._run((
            self.PACMAN, "--root", str(root),
            "--query", "--list", "--", name,
        ))
        if result.returncode != 0:
            raise RuntimeError(f"cannot enumerate certified package paths:{name}")
        paths: list[str] = []
        for line in result.stdout.splitlines():
            observed, sep, value = line.partition(" ")
            if sep and observed == name and value.startswith("/"):
                paths.append(self._canonical_rooted_package_path(root, value))
        if not paths:
            raise RuntimeError(f"certified package path set empty:{name}")
        return tuple(sorted(set(paths)))

    @staticmethod
    def _xattrs(path: Path) -> tuple[tuple[str, str], ...]:
        rows: list[tuple[str, str]] = []
        for name in sorted(os.listxattr(path, follow_symlinks=False)):
            rows.append((name, os.getxattr(path, name, follow_symlinks=False).hex()))
        return tuple(rows)

    def _compare_path(self, candidate_root: Path, relative: str, actual_root: Path = Path("/")) -> bool:
        rel = relative.lstrip("/")
        expected = candidate_root / rel
        actual = actual_root / rel
        try:
            left = expected.lstat()
            right = actual.lstat()
            if stat.S_IFMT(left.st_mode) != stat.S_IFMT(right.st_mode):
                return False
            if (
                stat.S_IMODE(left.st_mode) != stat.S_IMODE(right.st_mode)
                or left.st_uid != right.st_uid
                or left.st_gid != right.st_gid
                or self._xattrs(expected) != self._xattrs(actual)
            ):
                return False
            if stat.S_ISLNK(left.st_mode):
                return os.readlink(expected) == os.readlink(actual)
            if stat.S_ISDIR(left.st_mode):
                return True
            if stat.S_ISREG(left.st_mode):
                return left.st_size == right.st_size and self._hash(expected) == self._hash(actual)
            return left.st_rdev == right.st_rdev
        except (OSError, UnicodeError):
            return False

    def verify(self, plan: NormalExecutionPlan) -> Mapping[str, Any]:
        if self.roots is None or self.admission is None:
            return {"ok": False, "reason": "normal admission evidence missing"}
        observed = self._query_versions()
        if observed != self.expected:
            return {"ok": False, "reason": "live package version verification failed", "observed": observed, "expected": self.expected}
        candidate_root = self.roots.candidate_root
        path_set = self._path_set_evidence(candidate_root)
        if path_set["ok"] is not True:
            return {"ok": False, "reason": "live package path set diverged from admitted candidate", "path_set": path_set}
        payloads = self._payloads(plan)
        in_place = self._in_place_upgrade_profile(payloads)
        if in_place.get("ok") is not True:
            return {"ok": False, "reason": "in-place package profile drifted before final verification", "in_place_profile": in_place}
        hook_profile = self._hook_profile(payloads)
        if hook_profile.get("ok") is not True:
            return {"ok": False, "reason": "ALPM hook policy drifted before final verification", "hook_profile": hook_profile}
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
            "path_set": path_set,
            "in_place_profile": in_place,
            "hook_profile": hook_profile,
            "graph_id": str(self.admission.inspection.graph.graph_id),
            "base_root_identity": self.admission.inspection.base_root_identity,
            "candidate_root_identity": self.admission.inspection.candidate_root_identity,
        }
        self.last_verification = result
        return result

    def cleanup_success(self) -> Mapping[str, Any]:
        return self.btrfs.cleanup_candidate(str(self.candidate["uuid"]))
