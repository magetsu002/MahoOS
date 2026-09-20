#!/usr/bin/env python3
"""Package provenance and exact-artifact effect classification for Maho Update."""
from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

BOOT_CRITICAL_ROLES = frozenset({
    "kernel", "kernel-headers", "primary-kernel", "fallback-kernel",
    "primary-headers", "fallback-headers", "dkms", "initramfs",
    "boot-artifacts", "microcode", "bootloader", "boot-policy", "nvidia-kernel",
})

_BOOT_PREFIXES = (
    "/boot/",
    "/efi/",
    "/usr/lib/modules/",
    "/usr/lib/initcpio/",
    "/usr/lib/kernel/",
    "/usr/lib/systemd/boot/",
    "/usr/share/limine/",
)
_BOOT_EXACT_PREFIXES = (
    "/etc/mkinitcpio",
    "/etc/limine",
)
_SYSTEM_SERVICE_PREFIXES = (
    "/etc/systemd/system/",
    "/usr/lib/systemd/system/",
)
_USER_SERVICE_PREFIXES = (
    "/etc/systemd/user/",
    "/usr/lib/systemd/user/",
)
_DESKTOP_SESSION_PREFIXES = (
    "/usr/share/wayland-sessions/",
    "/usr/share/xsessions/",
    "/usr/share/xdg-desktop-portal/",
)
_SHARED_LIBRARY_PREFIXES = (
    "/usr/lib/",
    "/usr/lib32/",
)


def repository_provenance(repository: str) -> dict[str, str]:
    if not isinstance(repository, str) or not repository:
        raise ValueError("repository provenance requires repository identity")
    return {
        "kind": "repository",
        "repository": repository,
        "verification": "pacman-signature-policy",
    }


def aur_build_provenance(*, package_base: str, source_sha256: str, build_receipt: str) -> dict[str, str]:
    if not all(isinstance(value, str) and value for value in (package_base, source_sha256, build_receipt)):
        raise ValueError("AUR build provenance is incomplete")
    if len(source_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in source_sha256):
        raise ValueError("AUR source digest is invalid")
    return {
        "kind": "aur-built",
        "package_base": package_base,
        "source_sha256": source_sha256,
        "build_receipt": build_receipt,
        "verification": "maho-isolated-build",
    }


def validate_provenance(value: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(value)
    kind = data.get("kind")
    if kind == "repository":
        expected = repository_provenance(str(data.get("repository", "")))
        if data.get("verification") != expected["verification"]:
            raise ValueError("repository provenance verification is invalid")
        return expected
    if kind == "aur-built":
        return aur_build_provenance(
            package_base=str(data.get("package_base", "")),
            source_sha256=str(data.get("source_sha256", "")),
            build_receipt=str(data.get("build_receipt", "")),
        )
    raise ValueError("package provenance kind is invalid")


def _normalise_package_path(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("package file path is invalid")
    path = value.strip()
    if not path.startswith("/"):
        path = "/" + path
    # PurePosixPath collapses duplicate slashes/dots without consulting host FS.
    normal = "/" + str(PurePosixPath(path)).lstrip("/")
    if normal == "/.." or normal.startswith("/../"):
        raise ValueError("package file path escapes root")
    return normal


def preliminary_boot_critical(roles: Sequence[str]) -> bool:
    return bool(set(roles) & BOOT_CRITICAL_ROLES)


def classify_artifact(*, package_name: str, roles: Sequence[str], files: Iterable[str]) -> dict[str, Any]:
    paths = sorted({_normalise_package_path(item) for item in files})
    if not paths:
        raise ValueError("exact artifact file inventory is required")
    effects: set[str] = set()
    evidence: dict[str, list[str]] = {}

    def note(effect: str, path: str) -> None:
        effects.add(effect)
        bucket = evidence.setdefault(effect, [])
        if len(bucket) < 32:
            bucket.append(path)

    role_set = set(roles)
    if "maho-runtime" in role_set:
        effects.add("maho-runtime")
        evidence["maho-runtime-role"] = ["maho-runtime"]
    if role_set & BOOT_CRITICAL_ROLES:
        effects.add("boot-critical")
        evidence["boot-critical-role"] = sorted(role_set & BOOT_CRITICAL_ROLES)
    for path in paths:
        lowered = path.lower()
        if path.startswith(_BOOT_PREFIXES) or path.startswith(_BOOT_EXACT_PREFIXES):
            note("boot-critical", path)
        if path.startswith("/usr/share/libalpm/hooks/") and any(
            token in lowered for token in ("mkinitcpio", "kernel", "dkms", "microcode", "limine", "boot")
        ):
            note("boot-critical", path)
            note("package-hook", path)
        elif path.startswith("/usr/share/libalpm/hooks/"):
            note("package-hook", path)
        if path.startswith(_SYSTEM_SERVICE_PREFIXES):
            note("system-service", path)
        if path.startswith(_USER_SERVICE_PREFIXES):
            note("user-service", path)
        if path.startswith(_DESKTOP_SESSION_PREFIXES):
            note("desktop-session", path)
        if path.startswith(_SHARED_LIBRARY_PREFIXES) and any(
            part.endswith((".so", ".so.0", ".so.1", ".so.2", ".so.3")) or ".so." in part
            for part in PurePosixPath(path).parts
        ):
            note("shared-library", path)
    if not effects:
        effects.add("ordinary-files")

    activation: set[str] = set()
    if "boot-critical" in effects:
        activation.update({"initramfs-or-boot-refresh", "explicit-reboot"})
    if "system-service" in effects:
        activation.add("affected-system-service-restart")
    if effects & {"user-service", "desktop-session"}:
        activation.add("affected-user-session-restart")
    if "shared-library" in effects:
        activation.add("affected-process-restart")
    if "maho-runtime" in effects:
        activation.add("maho-runtime-release")

    encoded = json.dumps(paths, separators=(",", ":")).encode()
    return {
        "classification": "boot-critical" if "boot-critical" in effects else "normal",
        "effects": sorted(effects),
        "activation_requirements": sorted(activation),
        "file_count": len(paths),
        "files_sha256": hashlib.sha256(encoded).hexdigest(),
        "evidence": {key: value for key, value in sorted(evidence.items())},
        "package": package_name,
    }


def aggregate_effects(payloads: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    effects: set[str] = set()
    activation: set[str] = set()
    boot_packages: list[str] = []
    normal_packages: list[str] = []
    for payload in payloads:
        analysis = payload.get("effects")
        if not isinstance(analysis, Mapping):
            raise ValueError("staged payload effect analysis is missing")
        classification = analysis.get("classification")
        name = payload.get("name")
        if classification not in {"normal", "boot-critical"} or not isinstance(name, str) or not name:
            raise ValueError("staged payload effect classification is invalid")
        effects.update(str(item) for item in analysis.get("effects", []))
        activation.update(str(item) for item in analysis.get("activation_requirements", []))
        (boot_packages if classification == "boot-critical" else normal_packages).append(name)
    return {
        "classification": "boot-critical" if boot_packages else "normal",
        "effects": sorted(effects),
        "activation_requirements": sorted(activation),
        "boot_critical_packages": sorted(boot_packages),
        "normal_packages": sorted(normal_packages),
    }
