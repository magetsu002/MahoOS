#!/usr/bin/env python3
"""Canonical protected mutation scope built on Guardian effect taxonomy.

This module classifies targets, not command strings.  It deliberately does not
protect all of /home: only exact Maho runtime authority beneath an explicitly
configured home is eligible for protection there.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
import posixpath
from typing import Mapping

from guardian_admission import EffectKind, SECURITY_BOUNDARY_EFFECTS, classify_effect


class ProtectedDomain(str, Enum):
    ROOT = "root-filesystem"
    BOOT = "boot-authority"
    KERNEL = "kernel-authority"
    GUARDIAN = "guardian-authority"
    RECOVERY = "recovery-authority"
    GENERATION = "generation-authority"
    PACKAGE = "package-authority"
    PRIVILEGE = "privilege-authority"
    LOADER = "loader-policy"
    PERSISTENCE = "startup-persistence"
    SERVICE = "system-service-authority"


@dataclass(frozen=True)
class TargetContext:
    root_device: str | None = None
    boot_device: str | None = None
    owner_home: str | None = None
    mount_target: str | None = None


@dataclass(frozen=True)
class ScopeMatch:
    protected: bool
    domain: ProtectedDomain | None
    effect: EffectKind
    target: str
    reason: str
    recursive: bool = False


_DOMAIN_FOR_EFFECT: Mapping[EffectKind, ProtectedDomain] = {
    EffectKind.BOOT_STATE: ProtectedDomain.BOOT,
    EffectKind.KERNEL_MODULE: ProtectedDomain.KERNEL,
    EffectKind.PRIVILEGE_AUTHORITY: ProtectedDomain.PRIVILEGE,
    EffectKind.LOADER_POLICY: ProtectedDomain.LOADER,
    EffectKind.STARTUP_PERSISTENCE: ProtectedDomain.PERSISTENCE,
    EffectKind.PACMAN_HOOK: ProtectedDomain.PACKAGE,
    EffectKind.PACKAGE_FILE_OVERRIDE: ProtectedDomain.PACKAGE,
    EffectKind.SYSTEM_SERVICE: ProtectedDomain.SERVICE,
}

_EFFECT_FOR_DOMAIN: Mapping[ProtectedDomain, EffectKind] = {
    ProtectedDomain.BOOT: EffectKind.BOOT_STATE,
    ProtectedDomain.KERNEL: EffectKind.KERNEL_MODULE,
    ProtectedDomain.GUARDIAN: EffectKind.PRIVILEGE_AUTHORITY,
    ProtectedDomain.RECOVERY: EffectKind.BOOT_STATE,
    ProtectedDomain.GENERATION: EffectKind.BOOT_STATE,
    ProtectedDomain.PACKAGE: EffectKind.PACKAGE_FILE_OVERRIDE,
}

_EXACT_PREFIXES: tuple[tuple[str, ProtectedDomain], ...] = (
    ("/var/lib/maho/guardian", ProtectedDomain.GUARDIAN),
    ("/var/lib/maho/recovery", ProtectedDomain.RECOVERY),
    ("/var/lib/maho/guardian-recovery", ProtectedDomain.RECOVERY),
    ("/var/lib/maho/generations", ProtectedDomain.GENERATION),
    ("/var/lib/maho/boot-authority", ProtectedDomain.BOOT),
    ("/var/lib/pacman", ProtectedDomain.PACKAGE),
    ("/usr/lib/maho", ProtectedDomain.GUARDIAN),
    ("/boot", ProtectedDomain.BOOT),
    ("/efi", ProtectedDomain.BOOT),
)


def normalize_target(path: str) -> str:
    if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
        raise ValueError("mutation target must be an absolute path")
    normalized = posixpath.normpath(path)
    if normalized != path.rstrip("/") and not (path == "/" and normalized == "/"):
        raise ValueError("mutation target must already be normalized")
    return normalized


def _beneath(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def classify_target(path: str, *, context: TargetContext = TargetContext()) -> ScopeMatch:
    target = normalize_target(path)
    if target == "/":
        return ScopeMatch(True, ProtectedDomain.ROOT, EffectKind.FILE, target, "running_root_filesystem", True)
    for device, domain, reason in (
        (context.root_device, ProtectedDomain.ROOT, "live_root_block_device"),
        (context.boot_device, ProtectedDomain.BOOT, "boot_authority_block_device"),
    ):
        if device and target == os.path.normpath(device):
            return ScopeMatch(True, domain, EffectKind.BOOT_STATE if domain is ProtectedDomain.BOOT else EffectKind.FILE, target, reason)
    if context.mount_target and target == posixpath.normpath(context.mount_target) and target in {"/", "/boot", "/efi"}:
        domain = ProtectedDomain.ROOT if target == "/" else ProtectedDomain.BOOT
        return ScopeMatch(True, domain, EffectKind.BOOT_STATE if domain is ProtectedDomain.BOOT else EffectKind.FILE, target, "protected_mount_authority", True)
    for prefix, domain in _EXACT_PREFIXES:
        if _beneath(target, prefix):
            effect = classify_effect(target)
            if effect is EffectKind.FILE:
                effect = _EFFECT_FOR_DOMAIN.get(domain, effect)
            return ScopeMatch(True, domain, effect, target, f"protected_{domain.value}", True)
    if context.owner_home:
        home = normalize_target(context.owner_home)
        runtime = home + "/.local/share/maho/runtime"
        if _beneath(target, runtime):
            return ScopeMatch(True, ProtectedDomain.GUARDIAN, EffectKind.FILE, target, "immutable_maho_runtime_authority", True)
    effect = classify_effect(target)
    domain = _DOMAIN_FOR_EFFECT.get(effect)
    if effect in SECURITY_BOUNDARY_EFFECTS and domain is not None:
        return ScopeMatch(True, domain, effect, target, f"guardian_{effect.value.lower()}")
    return ScopeMatch(False, None, effect, target, "outside_protected_system_scope")
