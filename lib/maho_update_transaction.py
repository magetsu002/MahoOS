#!/usr/bin/env python3
"""Offline-first Maho Update transaction orchestration behind native gates."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Protocol, Sequence

from maho_runtime_release import verify_release
from maho_update_discovery import CommandResult
from maho_update_staging import validate_manifest
from maho_update_state import (
    UpdateState,
    transition_transaction,
    validate_transaction,
    write_transaction,
)

_PACKAGE = re.compile(r"[a-zA-Z0-9@._+:-]+")


class ExecutionFailure(RuntimeError):
    def __init__(
        self,
        stage: str,
        message: str,
        *,
        mutation_started: bool = False,
        evidence: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.mutation_started = mutation_started
        self.evidence = dict(evidence or {})


@dataclass(frozen=True)
class ExecutionPlan:
    transaction_id: str
    package_generation_id: str
    source_revision: str
    payload_paths: tuple[str, ...]
    maho_runtime: Mapping[str, Any]
    primary_kernel: Mapping[str, str]
    fallback_kernel: Mapping[str, str]
    primary_headers: Mapping[str, str]
    fallback_headers: Mapping[str, str]
    nvidia_dkms: Mapping[str, Any]
    initramfs_presets: tuple[str, str]
    boot_artifacts: tuple[str, ...]
    recovery_generation_id: str
    activation_requirements: tuple[str, ...]
    execution_environment: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionResult:
    transaction: dict[str, Any]
    plan: ExecutionPlan
    mutation_started: bool
    recovery_attempted: bool
    reboot_performed: bool = False
    firmware_mutated: bool = False


class UpdateExecutionOps(Protocol):
    def prepare_recovery(self, plan: ExecutionPlan) -> Mapping[str, Any]: ...
    def install_full_upgrade(self, plan: ExecutionPlan) -> Mapping[str, Any]: ...
    def verify_maho_runtime(self, plan: ExecutionPlan) -> Mapping[str, Any]: ...
    def verify_kernel_matrix(self, plan: ExecutionPlan) -> Mapping[str, Any]: ...
    def build_initramfs(self, plan: ExecutionPlan, preset: str) -> Mapping[str, Any]: ...
    def verify_boot_artifacts(self, plan: ExecutionPlan) -> Mapping[str, Any]: ...
    def finalize_install(self, plan: ExecutionPlan) -> Mapping[str, Any]: ...
    def recover(self, plan: ExecutionPlan, failed_stage: str) -> Mapping[str, Any]: ...
    def verify_activation(self, plan: ExecutionPlan) -> Mapping[str, Any]: ...


class OfflineRootUpdateOps:
    """Concrete non-live-root executor used by certified native update authority."""

    fixture_safe = False
    production_safe = True
    PACMAN = "/usr/bin/pacman"
    CHROOT = "/usr/bin/chroot"

    def __init__(self, offline_root: str | os.PathLike[str], cache_root: str | os.PathLike[str], *, runner=None) -> None:
        root = Path(offline_root)
        cache = Path(cache_root)
        if not root.is_absolute() or root.resolve(strict=False) == Path("/"):
            raise ValueError("offline update root must be an absolute non-live root")
        if not cache.is_absolute() or cache.resolve(strict=False) == Path("/var/cache/pacman/pkg"):
            raise ValueError("offline update cache must not be the live Pacman cache")
        self.root = root.resolve(strict=False)
        self.cache = cache.resolve(strict=False)
        self.db = self.root / "var/lib/pacman"
        self.runner = runner or self._system_run
        self.commands: list[tuple[str, ...]] = []

    @staticmethod
    def _system_run(command: Sequence[str]) -> CommandResult:
        completed = subprocess.run(
            list(command), check=False, text=True, capture_output=True,
            env={"PATH": "/usr/bin", "LC_ALL": "C"},
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)

    def install_command(self, plan: ExecutionPlan) -> tuple[str, ...]:
        payloads = tuple(str(Path(path).resolve(strict=False)) for path in plan.payload_paths)
        if not payloads or any(Path(path).parent != self.cache for path in payloads):
            raise ValueError("offline install payload escapes isolated cache")
        return (
            self.PACMAN, "--root", str(self.root), "--dbpath", str(self.db),
            "--cachedir", str(self.cache), "--upgrade", "--noconfirm", "--needed", "--", *payloads,
        )

    def query_command(self, plan: ExecutionPlan) -> tuple[str, ...]:
        packages = (
            plan.primary_kernel["package"], plan.primary_headers["package"],
            plan.fallback_kernel["package"], plan.fallback_headers["package"],
            *plan.nvidia_dkms["packages"],
        )
        return (self.PACMAN, "--root", str(self.root), "--dbpath", str(self.db), "--query", "--", *packages)

    def initramfs_command(self, preset: str) -> tuple[str, ...]:
        if preset not in {"linux-cachyos", "linux-cachyos-lts"}:
            raise ValueError("initramfs preset is outside the Primary/Fallback matrix")
        return (self.CHROOT, str(self.root), "/usr/bin/mkinitcpio", "-p", preset)

    def _allowed(self, command: Sequence[str], plan: ExecutionPlan) -> bool:
        argv = tuple(command)
        return argv in {self.install_command(plan), self.query_command(plan), *(self.initramfs_command(item) for item in plan.initramfs_presets)}

    def run(self, command: Sequence[str], plan: ExecutionPlan) -> CommandResult:
        if not self._allowed(command, plan):
            raise PermissionError(f"offline update command is not allowlisted: {tuple(command)!r}")
        self.commands.append(tuple(command))
        return self.runner(tuple(command))

    def _failure_evidence(self, stage: str, result: CommandResult) -> dict[str, Any]:
        """Persist exact command output outside the disposable candidate root."""
        safe_stage = re.sub(r"[^a-zA-Z0-9._-]", "-", stage)
        evidence_root = self.cache / ".execution-evidence"
        evidence_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if evidence_root.is_symlink() or not evidence_root.is_dir():
            raise RuntimeError("execution evidence directory is unsafe")
        payload = json.dumps(
            {
                "exit_code": result.returncode,
                "stderr": result.stderr,
                "stdout": result.stdout,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        destination = evidence_root / f"{safe_stage}.json"
        temporary = evidence_root / f".{safe_stage}.{os.getpid()}.tmp"
        try:
            with temporary.open("xb") as stream:
                os.chmod(temporary, 0o600)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            directory_fd = os.open(evidence_root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary.exists():
                temporary.unlink()
        return {
            "path": str(destination),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }

    def prepare_recovery(self, plan: ExecutionPlan) -> Mapping[str, Any]:
        marker = self.root / ".maho-recovery-generation"
        try:
            observed = marker.read_text(encoding="utf-8").strip()
        except OSError:
            observed = ""
        return {"ok": observed == plan.recovery_generation_id, "generation_id": observed}

    def install_full_upgrade(self, plan: ExecutionPlan) -> Mapping[str, Any]:
        result = self.run(self.install_command(plan), plan)
        evidence = {"ok": result.returncode == 0, "exit_code": result.returncode, "mutation_started": True}
        if result.returncode != 0:
            evidence["failure_evidence"] = self._failure_evidence("full-package-upgrade", result)
        return evidence

    def verify_maho_runtime(self, plan: ExecutionPlan) -> Mapping[str, Any]:
        releases = self.root / "usr/lib/maho/releases"
        verification = verify_release(releases / "current", releases)
        return {"ok": verification.verified, "verification": verification.as_dict()}

    def verify_kernel_matrix(self, plan: ExecutionPlan) -> Mapping[str, Any]:
        result = self.run(self.query_command(plan), plan)
        observed: dict[str, str] = {}
        for line in result.stdout.splitlines():
            name, separator, version = line.partition(" ")
            if separator:
                observed[name] = version.strip()
        expected = {
            item["package"]: item["version"] for item in (
                plan.primary_kernel, plan.primary_headers, plan.fallback_kernel, plan.fallback_headers,
            )
        }
        ok = result.returncode == 0 and all(observed.get(name) == version for name, version in expected.items())
        evidence = {"ok": ok, "observed": observed}
        if result.returncode != 0:
            evidence["failure_evidence"] = self._failure_evidence("kernel-header-dkms", result)
        return evidence

    def build_initramfs(self, plan: ExecutionPlan, preset: str) -> Mapping[str, Any]:
        result = self.run(self.initramfs_command(preset), plan)
        evidence = {"ok": result.returncode == 0, "preset": preset, "exit_code": result.returncode}
        if result.returncode != 0:
            evidence["failure_evidence"] = self._failure_evidence(f"initramfs-{preset}", result)
        return evidence

    def verify_boot_artifacts(self, plan: ExecutionPlan) -> Mapping[str, Any]:
        hashes: dict[str, str] = {}
        for artifact in plan.boot_artifacts:
            path = self.root / artifact.lstrip("/")
            if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
                return {"ok": False, "missing_or_unsafe": artifact}
            hashes[artifact] = hashlib.sha256(path.read_bytes()).hexdigest()
        return {"ok": True, "sha256": hashes}

    def finalize_install(self, plan: ExecutionPlan) -> Mapping[str, Any]:
        return {"ok": True, "activation_required": list(plan.activation_requirements)}

    def recover(self, plan: ExecutionPlan, failed_stage: str) -> Mapping[str, Any]:
        return {"ok": False, "reason": "native recovery execution remains an M3B/M4B authority"}

    def verify_activation(self, plan: ExecutionPlan) -> Mapping[str, Any]:
        return {"ok": False, "reason": "native activation verification remains M4B"}


def _relationship(value: Any, expected_package: str, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} relationship is required")
    package = value.get("package")
    version = value.get("version")
    if package != expected_package or not isinstance(version, str) or not version:
        raise ValueError(f"{name} relationship is invalid")
    return {"package": package, "version": version}


def build_execution_plan(
    transaction: Mapping[str, Any],
    manifest: Mapping[str, Any],
    cache_root: str | Path,
    relationships: Mapping[str, Any],
    *,
    execution_environment: str,
) -> ExecutionPlan:
    current = validate_transaction(transaction)
    if current["state"] != UpdateState.MAINTENANCE_READY.value:
        raise ValueError("execution plan requires MAINTENANCE_READY authority")
    verified_manifest = validate_manifest(manifest, current, Path(cache_root))
    if execution_environment not in {"production", "fixture"}:
        raise ValueError("execution environment is invalid")
    primary = _relationship(relationships.get("primary_kernel"), "linux-cachyos", "Primary kernel")
    fallback = _relationship(relationships.get("fallback_kernel"), "linux-cachyos-lts", "Fallback kernel")
    primary_headers = _relationship(relationships.get("primary_headers"), "linux-cachyos-headers", "Primary headers")
    fallback_headers = _relationship(relationships.get("fallback_headers"), "linux-cachyos-lts-headers", "Fallback headers")
    if primary["version"] != primary_headers["version"]:
        raise ValueError("Primary kernel/header version mismatch")
    if fallback["version"] != fallback_headers["version"]:
        raise ValueError("Fallback kernel/header version mismatch")
    runtime = relationships.get("maho_runtime")
    if not isinstance(runtime, Mapping) or runtime.get("immutable_release_required") is not True:
        raise ValueError("immutable Maho runtime relationship is required")
    runtime_package = runtime.get("package")
    runtime_version = runtime.get("version")
    if not isinstance(runtime_package, str) or _PACKAGE.fullmatch(runtime_package) is None or not isinstance(runtime_version, str) or not runtime_version:
        raise ValueError("Maho runtime relationship is invalid")
    nvidia = relationships.get("nvidia_dkms")
    if not isinstance(nvidia, Mapping) or nvidia.get("status") not in {"planned", "not-installed"}:
        raise ValueError("NVIDIA/DKMS relationship is unknown")
    packages = nvidia.get("packages", [])
    if not isinstance(packages, list) or any(not isinstance(item, str) or _PACKAGE.fullmatch(item) is None for item in packages):
        raise ValueError("NVIDIA/DKMS package identity is invalid")
    artifacts = relationships.get("boot_artifacts")
    required_artifacts = {
        "/boot/intel-ucode.img",
        "/boot/vmlinuz-linux-cachyos", "/boot/initramfs-linux-cachyos.img",
        "/boot/vmlinuz-linux-cachyos-lts", "/boot/initramfs-linux-cachyos-lts.img",
    }
    if not isinstance(artifacts, list) or set(artifacts) != required_artifacts:
        raise ValueError("both Primary and Fallback boot artifacts are required")
    recovery = current["recovery"]["generation_id"]
    if not isinstance(recovery, str) or not recovery.startswith("g3-"):
        raise ValueError("execution plan requires exact recovery generation")
    return ExecutionPlan(
        transaction_id=current["transaction_id"],
        package_generation_id=current["package_generation"]["id"],
        source_revision=current["source_revision"],
        payload_paths=tuple(item["path"] for item in verified_manifest["payloads"]),
        maho_runtime=dict(runtime),
        primary_kernel=primary,
        fallback_kernel=fallback,
        primary_headers=primary_headers,
        fallback_headers=fallback_headers,
        nvidia_dkms={"status": nvidia["status"], "packages": list(packages)},
        initramfs_presets=("linux-cachyos", "linux-cachyos-lts"),
        boot_artifacts=tuple(sorted(artifacts)),
        recovery_generation_id=recovery,
        activation_requirements=tuple(current["activation"]["requirements"]),
        execution_environment=execution_environment,
    )


def _require_ok(evidence: Mapping[str, Any], stage: str) -> dict[str, Any]:
    if not isinstance(evidence, Mapping) or evidence.get("ok") is not True:
        mutation_started = isinstance(evidence, Mapping) and evidence.get("mutation_started") is True
        details = dict(evidence) if isinstance(evidence, Mapping) else {}
        json.dumps(details, sort_keys=True)
        raise ExecutionFailure(
            stage,
            f"{stage} did not produce positive bounded evidence",
            mutation_started=mutation_started,
            evidence=details,
        )
    json.dumps(evidence, sort_keys=True)
    return dict(evidence)


def _invoke(stage: str, function) -> dict[str, Any]:
    try:
        return _require_ok(function(), stage)
    except ExecutionFailure:
        raise
    except Exception as exc:
        raise ExecutionFailure(stage, str(exc)) from exc


def _persist(path: Path | None, transaction: Mapping[str, Any]) -> None:
    if path is not None:
        write_transaction(path, transaction)


def _recover_failure(
    installing: Mapping[str, Any],
    plan: ExecutionPlan,
    ops: UpdateExecutionOps,
    failure: ExecutionFailure,
    *,
    mutation_started: bool,
    journal_path: Path | None,
    now=None,
) -> ExecutionResult:
    mutation_started = mutation_started or failure.mutation_started
    failure_evidence: dict[str, Any] = {"stage": failure.stage, "error": str(failure)}
    if failure.evidence:
        failure_evidence["details"] = failure.evidence
    if not mutation_started:
        failed = transition_transaction(
            installing, UpdateState.FAILED_RECOVERABLE,
            reason=f"update failed before package mutation: {failure.stage}",
            evidence=failure_evidence, now=now,
        )
        _persist(journal_path, failed)
        return ExecutionResult(failed, plan, False, False)
    recovering = transition_transaction(
        installing, UpdateState.RECOVERING,
        reason=f"bounded recovery started after {failure.stage}",
        evidence=failure_evidence, now=now,
    )
    _persist(journal_path, recovering)
    try:
        recovered_evidence = _require_ok(ops.recover(plan, failure.stage), "recovery")
    except (ExecutionFailure, Exception) as recovery_error:
        attention = transition_transaction(
            recovering, UpdateState.ATTENTION_REQUIRED,
            reason="update recovery failed and requires explicit handoff",
            blockers=["update_recovery_failed"],
            evidence={"failed_stage": failure.stage, "error": str(recovery_error)}, now=now,
        )
        _persist(journal_path, attention)
        return ExecutionResult(attention, plan, True, True)
    recovered = transition_transaction(
        recovering, UpdateState.RECOVERED,
        reason="bounded recovery restored the protected pre-update state",
        evidence=recovered_evidence, now=now,
    )
    _persist(journal_path, recovered)
    return ExecutionResult(recovered, plan, True, True)


def execute_update(
    transaction: Mapping[str, Any],
    plan: ExecutionPlan,
    ops: UpdateExecutionOps,
    *,
    native_l3_certified: bool = False,
    native_update_execution_certified: bool = False,
    journal_path: Path | None = None,
    now=None,
) -> ExecutionResult:
    current = validate_transaction(transaction)
    # Legacy caller booleans are deliberately not authority. M4B reads only the
    # source-bound durable certification records inside the transaction.
    _ = (native_l3_certified, native_update_execution_certified)
    if current["state"] != UpdateState.MAINTENANCE_READY.value:
        raise ValueError("update execution requires MAINTENANCE_READY authority")
    if current["transaction_id"] != plan.transaction_id or current["package_generation"]["id"] != plan.package_generation_id:
        raise ValueError("execution plan does not bind the exact transaction")
    if plan.source_revision != current["source_revision"]:
        raise ValueError("execution source revision drifted")
    if plan.execution_environment == "production":
        blockers: list[str] = []
        if current["recovery"]["native_l3_certified"] is not True:
            blockers.append("native_l3_certification_required")
        if current["activation"]["native_execution_certified"] is not True:
            blockers.append("native_update_execution_uncertified")
        if blockers:
            blocked = transition_transaction(
                current, UpdateState.BLOCKED,
                reason="production update mutation requires durable M3B/M4B authority",
                blockers=blockers, now=now,
            )
            _persist(journal_path, blocked)
            return ExecutionResult(blocked, plan, False, False)
        if getattr(ops, "production_safe", False) is not True:
            blocked = transition_transaction(
                current, UpdateState.BLOCKED,
                reason="production execution requires the certified non-live-root provider",
                blockers=["production_executor_not_certified"], now=now,
            )
            _persist(journal_path, blocked)
            return ExecutionResult(blocked, plan, False, False)
    elif getattr(ops, "fixture_safe", False) is not True:
        blocked = transition_transaction(
            current, UpdateState.BLOCKED,
            reason="fixture execution requires a non-system fake provider",
            blockers=["fixture_executor_not_isolated"], now=now,
        )
        _persist(journal_path, blocked)
        return ExecutionResult(blocked, plan, False, False)

    installing = transition_transaction(
        current, UpdateState.INSTALLING,
        reason=("certified offline native transaction started" if plan.execution_environment == "production" else "offline fixture transaction started"),
        evidence={"plan": plan.as_dict()}, now=now,
    )
    _persist(journal_path, installing)
    mutation_started = False
    evidence: dict[str, Any] = {}
    try:
        evidence["recovery"] = _invoke("recovery-preparation", lambda: ops.prepare_recovery(plan))
        evidence["packages"] = _invoke("full-package-upgrade", lambda: ops.install_full_upgrade(plan))
        mutation_started = evidence["packages"].get("mutation_started", True) is True
        evidence["maho_runtime"] = _invoke("maho-runtime", lambda: ops.verify_maho_runtime(plan))
        evidence["kernel_matrix"] = _invoke("kernel-header-dkms", lambda: ops.verify_kernel_matrix(plan))
        initramfs: dict[str, Any] = {}
        for preset in plan.initramfs_presets:
            initramfs[preset] = _invoke(f"initramfs:{preset}", lambda preset=preset: ops.build_initramfs(plan, preset))
        evidence["initramfs"] = initramfs
        evidence["boot"] = _invoke("boot-artifacts", lambda: ops.verify_boot_artifacts(plan))
        evidence["final"] = _invoke("install-finalization", lambda: ops.finalize_install(plan))
    except ExecutionFailure as failure:
        return _recover_failure(
            installing, plan, ops, failure, mutation_started=mutation_started,
            journal_path=journal_path, now=now,
        )
    pending = transition_transaction(
        installing, UpdateState.INSTALLED_PENDING_ACTIVATION,
        reason="installation complete; activation requires a later explicit restart",
        evidence=evidence, now=now,
    )
    _persist(journal_path, pending)
    return ExecutionResult(pending, plan, True, False)


def verify_activation(
    transaction: Mapping[str, Any],
    plan: ExecutionPlan,
    ops: UpdateExecutionOps,
    *,
    journal_path: Path | None = None,
    now=None,
) -> ExecutionResult:
    current = validate_transaction(transaction)
    if current["state"] != UpdateState.INSTALLED_PENDING_ACTIVATION.value:
        raise ValueError("activation verification requires pending activation state")
    if plan.execution_environment == "production":
        if current["recovery"]["native_l3_certified"] is not True or current["activation"]["native_execution_certified"] is not True:
            raise ValueError("production activation verification requires durable native authority")
        if getattr(ops, "production_safe", False) is not True:
            raise ValueError("production activation verifier is not certified")
    elif getattr(ops, "fixture_safe", False) is not True:
        raise ValueError("fixture activation verification requires fixture-safe provider")
    verifying = transition_transaction(
        current, UpdateState.ACTIVE_VERIFYING,
        reason=("native activation proof started" if plan.execution_environment == "production" else "fixture activation proof started"),
        now=now,
    )
    _persist(journal_path, verifying)
    try:
        evidence = _invoke("activation-verification", lambda: ops.verify_activation(plan))
    except ExecutionFailure as failure:
        return _recover_failure(verifying, plan, ops, failure, mutation_started=True, journal_path=journal_path, now=now)
    healthy = transition_transaction(
        verifying, UpdateState.HEALTHY,
        reason="activated generation passed health verification", evidence=evidence, now=now,
    )
    _persist(journal_path, healthy)
    return ExecutionResult(healthy, plan, True, False)



def verify_fixture_activation(
    transaction: Mapping[str, Any],
    plan: ExecutionPlan,
    ops: UpdateExecutionOps,
    *,
    journal_path: Path | None = None,
    now=None,
) -> ExecutionResult:
    """Compatibility wrapper for the M4A fixture contract."""
    if plan.execution_environment != "fixture":
        return ExecutionResult(validate_transaction(transaction), plan, True, False)
    return verify_activation(transaction, plan, ops, journal_path=journal_path, now=now)

def recover_interrupted_fixture(
    transaction: Mapping[str, Any],
    plan: ExecutionPlan,
    ops: UpdateExecutionOps,
    *,
    journal_path: Path | None = None,
    now=None,
) -> ExecutionResult:
    current = validate_transaction(transaction)
    if current["state"] != UpdateState.INSTALLING.value or plan.execution_environment != "fixture":
        raise ValueError("only an interrupted fixture installation may be reconciled")
    failure = ExecutionFailure("interrupted-transaction", "durable journal ended while installing")
    return _recover_failure(current, plan, ops, failure, mutation_started=True, journal_path=journal_path, now=now)
