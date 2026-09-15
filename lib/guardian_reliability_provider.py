#!/usr/bin/env python3
"""Always-on read-only reliability evidence producer for Guardian."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any, Callable, Mapping

from guardian_evidence import ProviderHealth, utc_stamp
from guardian_provider_state import record_heartbeat
from guardian_recovery_registry import certified_service_units

SAMPLE_INTERVAL_SECONDS = 30.0


def _atomic_private(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _state_path(root: Path, provider_id: str) -> Path:
    suffix = provider_id.removeprefix("reliability.")
    return root / "guardian" / "reliability" / f"{suffix}.json"


def memory_facts(proc_root: Path = Path("/proc")) -> dict[str, Any]:
    values: dict[str, int] = {}
    for line in (proc_root / "meminfo").read_text(encoding="utf-8").splitlines():
        key, sep, raw = line.partition(":")
        if not sep:
            continue
        token = raw.strip().split()[0] if raw.strip() else ""
        if token.isdigit():
            values[key] = int(token)
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    if total <= 0 or available < 0:
        raise ValueError("memory totals unavailable")
    return {
        "total_kib": total,
        "available_kib": available,
        "available_percent": (available * 100.0 / total),
    }


def storage_facts(path: Path = Path("/")) -> dict[str, Any]:
    stat = os.statvfs(path)
    total = stat.f_blocks * stat.f_frsize
    available = stat.f_bavail * stat.f_frsize
    if total <= 0:
        raise ValueError("storage totals unavailable")
    used = max(0, total - available)
    return {
        "path": str(path),
        "total_bytes": total,
        "available_bytes": available,
        "used_percent": used * 100.0 / total,
    }


def service_facts(
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    services: list[dict[str, Any]] = []
    for unit in certified_service_units():
        result = runner(
            [
                "systemctl", "--user", "show", unit,
                "--property=LoadState", "--property=ActiveState",
                "--property=SubState", "--property=NRestarts",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            services.append({"unit": unit, "load_state": "unknown", "active_state": "unknown", "sub_state": "unknown", "restart_count": None})
            continue
        values: dict[str, str] = {}
        for line in result.stdout.splitlines():
            key, sep, value = line.partition("=")
            if sep:
                values[key] = value
        raw_restarts = values.get("NRestarts", "")
        services.append({
            "unit": unit,
            "load_state": values.get("LoadState", "unknown"),
            "active_state": values.get("ActiveState", "unknown"),
            "sub_state": values.get("SubState", "unknown"),
            "restart_count": int(raw_restarts) if raw_restarts.isdigit() else None,
        })
    return {"services": services}


def _persist_success(root: Path, provider_id: str, source: str, facts: Mapping[str, Any], boot_id: str | None) -> None:
    observed_at = utc_stamp(datetime.now(timezone.utc))
    _atomic_private(_state_path(root, provider_id), {
        "version": 1,
        "kind": "guardian-reliability-observation",
        "provider_id": provider_id,
        "observed_at": observed_at,
        "facts": dict(facts),
    })
    record_heartbeat(
        root,
        provider_id=provider_id,
        domain="reliability",
        source=source,
        authority_boundary="read-only-observer",
        success=True,
        health=ProviderHealth.HEALTHY,
        boot_id=boot_id,
        details={"state_path": str(_state_path(root, provider_id))},
    )


def _persist_failure(root: Path, provider_id: str, source: str, boot_id: str | None, exc: Exception) -> None:
    record_heartbeat(
        root,
        provider_id=provider_id,
        domain="reliability",
        source=source,
        authority_boundary="read-only-observer",
        success=False,
        health=ProviderHealth.FAILED,
        errors=(f"{type(exc).__name__}:{exc}",),
        boot_id=boot_id,
    )


def refresh_once(
    root: Path,
    *,
    boot_id: str | None,
    proc_root: Path = Path("/proc"),
    storage_path: Path = Path("/"),
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    samplers = (
        ("reliability.memory", "procfs-meminfo", lambda: memory_facts(proc_root)),
        ("reliability.storage", "statvfs", lambda: storage_facts(storage_path)),
        ("reliability.services", "systemd-user", lambda: service_facts(runner=runner)),
    )
    for provider_id, source, sampler in samplers:
        try:
            facts = sampler()
            _persist_success(root, provider_id, source, facts, boot_id)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            _persist_failure(root, provider_id, source, boot_id, exc)


def reliability_loop(root: Path, *, boot_id: str | None, interval: float = SAMPLE_INTERVAL_SECONDS) -> None:
    delay = max(5.0, float(interval))
    while True:
        refresh_once(root, boot_id=boot_id)
        time.sleep(delay)


def resolve_state_root(argv: list[str]) -> Path:
    try:
        index = argv.index("--state-root")
        return Path(argv[index + 1])
    except (ValueError, IndexError):
        return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "maho/security"
