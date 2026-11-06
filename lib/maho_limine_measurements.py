#!/usr/bin/env python3
"""Deterministic Limine-v12 PCR 8/9 predictions for an exact Linux boot entry.

No TPM access, no signing and no firmware/device mutation. Predictions are NOT
TPM attestations and are not complete without independent event-log replay and
comparison to the hardware PCR bank. See Limine v12 USAGE.md 'Measured Boot'.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Mapping

_HASH = re.compile(r"boot\(\):(/[^#\s]+)#([0-9a-f]{128})\Z")
_VERSION = re.compile(r"(\d+)(?:\.(\d+))?(?:\.\d+)*\Z")
_KEYS = {"protocol", "path", "kernel_path", "cmdline", "kernel_cmdline", "module_path"}


class MeasurementError(ValueError):
    pass


@dataclass(frozen=True)
class LimineMeasurement:
    entry: str
    kernel_cmdline: str
    config_sha256: str
    pcr8_limine_only: str
    pcr9_limine_only: str
    measured_resources: tuple[str, ...]
    pcr8_event_digests: tuple[str, ...]
    pcr9_event_digests: tuple[str, ...]


def _entry(config: bytes, title: str) -> tuple[dict[str, str], tuple[str, ...], bool]:
    try:
        lines = config.decode("utf-8", "strict").splitlines()
    except UnicodeDecodeError as exc:
        raise MeasurementError("limine_config_utf8_invalid") from exc
    global_values: dict[str, str] = {}
    selected: dict[str, str] | None = None
    selected_modules: tuple[str, ...] = ()
    current: dict[str, str] | None = None
    modules: list[str] = []
    found = 0
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("/"):
            if current is not None:
                selected, selected_modules = current, tuple(modules)
                current = None
            if line[1:] == title:
                found += 1
                current = {}
                modules = []
            continue
        if ":" not in line:
            raise MeasurementError("limine_config_syntax_invalid")
        key, value = (piece.strip() for piece in line.split(":", 1))
        if current is None:
            if found == 0 and key in {"measured_boot", "hash_mismatch_panic"}:
                if key in global_values:
                    raise MeasurementError("limine_global_option_duplicated")
                global_values[key] = value
            continue
        if key not in _KEYS:
            raise MeasurementError("limine_entry_option_unmodelled")
        if key == "module_path":
            modules.append(value)
        elif key in current:
            raise MeasurementError("limine_entry_option_duplicated")
        else:
            current[key] = value
    if current is not None:
        selected, selected_modules = current, tuple(modules)
    if found != 1 or selected is None:
        raise MeasurementError("limine_entry_not_unique")
    if selected.get("protocol") != "linux":
        raise MeasurementError("limine_protocol_unsupported")
    if sum(key in selected for key in ("path", "kernel_path")) != 1:
        raise MeasurementError("limine_kernel_path_ambiguous")
    if sum(key in selected for key in ("cmdline", "kernel_cmdline")) != 1:
        raise MeasurementError("limine_cmdline_ambiguous")
    if not selected_modules:
        raise MeasurementError("limine_initramfs_missing")
    if global_values.get("hash_mismatch_panic") == "no":
        raise MeasurementError("limine_hash_mismatch_panic_disabled")
    return selected, selected_modules, global_values.get("measured_boot") == "yes"


def _path(value: str, content: Mapping[str, bytes]) -> tuple[str, bytes]:
    match = _HASH.fullmatch(value)
    if match is None:
        raise MeasurementError("limine_resource_path_not_exact_and_hashed")
    path, expected = match.groups()
    if ".." in path.split("/") or "//" in path or "\x00" in path:
        raise MeasurementError("limine_resource_path_unsafe")
    raw = content.get(path)
    if not isinstance(raw, bytes) or not raw:
        raise MeasurementError("limine_resource_bytes_missing")
    if hashlib.blake2b(raw, digest_size=64).hexdigest() != expected:
        raise MeasurementError("limine_resource_integrity_mismatch")
    return value.rsplit("#", 1)[0], raw


def _replay(events: tuple[bytes, ...]) -> tuple[str, tuple[str, ...]]:
    pcr = bytes(32)
    digests: list[str] = []
    for event in events:
        digest = hashlib.sha256(event).digest()
        digests.append(digest.hex())
        pcr = hashlib.sha256(pcr + digest).digest()
    return pcr.hex(), tuple(digests)


def predict_limine_measurements(
    *, config: bytes, entry: str, resources: Mapping[str, bytes],
    limine_version: str, secure_boot_enforced: bool,
) -> LimineMeasurement:
    """Predict Limine-only PCR extensions from a fully specified entry.

    Firmware can extend additional PCR events. These outputs MUST NOT be
    treated as current TPM PCR values without independent firmware event-log
    replay, trustworthy PCR reads and a boot-identity match.
    """
    version = _VERSION.fullmatch(limine_version)
    if version is None or int(version.group(1)) < 12:
        raise MeasurementError("limine_version_unproven")
    selected, modules, explicit_measure = _entry(config, entry)
    if not (explicit_measure or secure_boot_enforced):
        raise MeasurementError("limine_measured_boot_inactive")
    kernel_value = selected.get("path", selected.get("kernel_path", ""))
    cmdline = selected.get("cmdline", selected.get("kernel_cmdline", ""))
    if not cmdline or "\x00" in cmdline:
        raise MeasurementError("limine_cmdline_invalid")
    kernel, kernel_raw = _path(kernel_value, resources)
    module_rows = tuple(_path(value, resources) for value in modules)
    pcr8_events = (("cmdline: " + cmdline).encode(), ("path: " + kernel).encode()) + tuple(
        ("module_path: " + path).encode() for path, _ in module_rows
    )
    pcr9_events = (config, kernel_raw) + tuple(raw for _, raw in module_rows)
    pcr8, d8 = _replay(pcr8_events)
    pcr9, d9 = _replay(pcr9_events)
    return LimineMeasurement(
        entry, cmdline, hashlib.sha256(config).hexdigest(), pcr8, pcr9,
        (kernel,) + tuple(path for path, _ in module_rows), d8, d9,
    )
