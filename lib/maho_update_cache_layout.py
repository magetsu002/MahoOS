#!/usr/bin/env python3
"""Update-owned selection of an explicitly provisioned, isolated Btrfs cache.

This observer never creates a mount, changes a manifest or migrates old bytes.
An unavailable isolated cache is a blocker, not an ordinary-directory fallback.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from maho_generation_gc import InventoryError, digest_payload, _atomic_json

CACHE = Path("/var/cache/maho/update-artifacts")
SUBVOLUME = "@maho-update-artifacts"
RECORD = Path("/var/lib/maho/update/cache-layout.json")
LEGACY_ROOTS = {"auto": Path("/var/cache/maho/update-auto"),
                "m4b": Path("/var/cache/maho/update-m4b")}
UNIT_NAME = "var-cache-maho-update\\x2dartifacts.mount"
UNIT_PATH = Path("/etc/systemd/system") / UNIT_NAME
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")


def _run(argv: tuple[str, ...]) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, check=False,
                            timeout=15, env={"PATH": "/usr/bin", "LC_ALL": "C"})
    if result.returncode:
        raise InventoryError("isolated cache observation failed: " + argv[0])
    return result.stdout


def _owned_bytes(path: Path, *, owner_uid: int = 0) -> bytes:
    # Validate every ancestor without following symlinks.
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd); fd = child
            st = os.fstat(fd)
            if st.st_uid != owner_uid or st.st_mode & 0o022:
                raise InventoryError("untrusted cache observation ancestor")
        child = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
        with os.fdopen(child, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != owner_uid
                    or before.st_mode & 0o022 or before.st_nlink != 1 or before.st_size > 65536):
                raise InventoryError("untrusted cache observation file")
            raw = stream.read()
            after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise InventoryError("cache observation changed during read")
            return raw
    finally:
        os.close(fd)


def mount_unit(filesystem_uuid: str) -> str:
    if not isinstance(filesystem_uuid, str) or UUID.fullmatch(filesystem_uuid) is None:
        raise InventoryError("invalid cache filesystem UUID")
    return ("[Unit]\nDescription=Maho isolated update artifacts\nBefore=maho-update-coordinator.service\n"
            "ConditionKernelCommandLine=!maho.recovery_snapshot=1\n\n[Mount]\n"
            f"What=/dev/disk/by-uuid/{filesystem_uuid}\nWhere={CACHE}\nType=btrfs\n"
            f"Options=subvol={SUBVOLUME},nodev,nosuid,noexec\n\n[Install]\nWantedBy=local-fs.target\n")


def validate_layout(record: Mapping[str, Any], *, probe: Callable = _run,
                    unit_bytes: bytes, observed_uid: int, observed_mode: int) -> dict[str, Any]:
    value = dict(record); claimed = value.pop("layout_sha256", None)
    if (claimed != digest_payload(value) or value.get("kind") != "maho-isolated-update-cache"
            or value.get("schema_version") != 1 or value.get("phase") != "COMMITTED"
            or value.get("path") != str(CACHE) or value.get("subvolume") != SUBVOLUME
            or not isinstance(value.get("filesystem_uuid"), str)
            or UUID.fullmatch(value["filesystem_uuid"]) is None
            or not isinstance(value.get("subvolume_uuid"), str)
            or UUID.fullmatch(value["subvolume_uuid"]) is None
            or not isinstance(value.get("source_revision"), str)
            or re.fullmatch(r"[0-9a-f]{40}", value["source_revision"]) is None):
        raise InventoryError("isolated cache record is incomplete or corrupt")
    if (observed_uid != 0 or observed_mode & 0o022
            or unit_bytes != mount_unit(value["filesystem_uuid"]).encode()
            or value.get("mount_unit_sha256") != hashlib.sha256(unit_bytes).hexdigest()):
        raise InventoryError("isolated cache owner or mount unit drifted")
    rows = json.loads(probe(("/usr/bin/findmnt", "--json", "--mountpoint", str(CACHE),
                             "--output", "TARGET,FSTYPE,FSROOT,UUID,OPTIONS"))).get("filesystems")
    row = rows[0] if isinstance(rows, list) and len(rows) == 1 else {}
    options = set(str(row.get("options", "")).split(","))
    if (row.get("target") != str(CACHE) or row.get("fstype") != "btrfs"
            or row.get("fsroot") != "/" + SUBVOLUME or row.get("uuid") != value["filesystem_uuid"]
            or not {"rw", "nodev", "nosuid", "noexec"} <= options):
        raise InventoryError("exact isolated cache mount is unavailable")
    root_rows = json.loads(probe(("/usr/bin/findmnt", "--json", "--target", "/",
                                  "--output", "TARGET,FSTYPE,FSROOT,UUID"))).get("filesystems")
    root = root_rows[0] if isinstance(root_rows, list) and len(root_rows) == 1 else {}
    if root.get("target") != "/" or root.get("fstype") != "btrfs" or root.get("uuid") != value["filesystem_uuid"]:
        raise InventoryError("cache is not on the independently observed root filesystem")
    shown = probe(("/usr/bin/btrfs", "subvolume", "show", str(CACHE)))
    fields = {key.strip(): val.strip() for line in shown.splitlines()
              if (key := line.partition(":")[0]) and (val := line.partition(":")[2])}
    if fields.get("UUID") != value["subvolume_uuid"]:
        raise InventoryError("isolated cache subvolume UUID drifted")
    readonly = probe(("/usr/bin/btrfs", "property", "get", "-ts", str(CACHE), "ro"))
    if readonly.strip() != "ro=false":
        raise InventoryError("isolated cache is not writable")
    return dict(record)


def observe_layout() -> dict[str, Any]:
    record = json.loads(_owned_bytes(RECORD))
    from maho_generation_gc import CertifiedFileGC
    guard = CertifiedFileGC(roots={"cache":CACHE}, state_root=RECORD.parent)
    fd = guard._trusted_directory(CACHE)
    try:
        st = os.fstat(fd)
        return validate_layout(record, unit_bytes=_owned_bytes(UNIT_PATH),
                               observed_uid=st.st_uid, observed_mode=st.st_mode)
    finally:
        os.close(fd)


def staging_root(lane: str) -> Path:
    if lane not in LEGACY_ROOTS:
        raise InventoryError("unknown isolated staging lane")
    observe_layout()
    root = CACHE / lane
    st = root.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
        raise InventoryError("isolated cache lane is unsafe")
    return root


def isolation_available() -> bool:
    observe_layout()
    return True


def retirement_roots() -> dict[str, Path]:
    # Legacy objects stay at their immutable manifest paths. The mount must be
    # verified before any object below the new path can enter a GC inventory.
    roots = dict(LEGACY_ROOTS)
    if RECORD.exists() or RECORD.is_symlink() or CACHE.exists() or CACHE.is_symlink():
        observe_layout()
        roots.update({"isolated-" + lane: staging_root(lane) for lane in LEGACY_ROOTS})
    return roots


def transaction_root(transaction_id: str, lane: str) -> Path:
    if not isinstance(transaction_id, str) or re.fullmatch(r"upd-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}", transaction_id) is None:
        raise InventoryError("invalid cache transaction identity")
    legacy = LEGACY_ROOTS[lane] / transaction_id
    isolated = CACHE / lane / transaction_id
    # Preserve exact legacy paths without migrating or reinterpreting manifests.
    # An ambiguous duplicate owner is never selected by preference.
    if legacy.exists() or legacy.is_symlink():
        if legacy.is_symlink() or not legacy.is_dir() or isolated.exists() or isolated.is_symlink():
            raise InventoryError("ambiguous or unsafe transaction cache owner")
        from maho_generation_gc import CertifiedFileGC
        guard = CertifiedFileGC(roots={"legacy":LEGACY_ROOTS[lane]}, state_root=RECORD.parent)
        fd = guard._trusted_directory(legacy); os.close(fd)
        return LEGACY_ROOTS[lane]
    return staging_root(lane)


def installation_plan(source_revision: str, filesystem_uuid: str, *, now=None) -> dict[str, Any]:
    if not isinstance(source_revision, str) or re.fullmatch(r"[0-9a-f]{40}", source_revision) is None:
        raise InventoryError("cache installation requires exact source")
    unit = mount_unit(filesystem_uuid)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise InventoryError("cache installation time is unresolved")
    value = {"kind": "maho-cache-installation-plan", "schema_version": 1,
             "source_revision": source_revision, "filesystem_uuid": filesystem_uuid,
             "path": str(CACHE), "subvolume": SUBVOLUME, "unit_path": str(UNIT_PATH),
             "mount_unit_sha256": hashlib.sha256(unit.encode()).hexdigest(),
             "created_at": current.isoformat(), "expires_at": (current + timedelta(minutes=5)).isoformat()}
    value["plan_sha256"] = digest_payload(value)
    return value


def install_cache(plan: Mapping[str, Any], *, confirmation: str, source_revision: str,
                  now=None) -> dict[str, Any]:
    """Explicit exact installation only; caller holds the campaign lock.

    No existing unknown target is adopted. A create/journal crash gap is kept
    unresolved rather than claiming ownership of an unrecorded subvolume.
    """
    from maho_update_native import NativeBtrfsOps
    if os.geteuid() != 0:
        raise PermissionError("cache installation requires explicit root authorization")
    current = now or datetime.now(timezone.utc)
    created = datetime.fromisoformat(str(plan.get("created_at")))
    expiry = datetime.fromisoformat(str(plan.get("expires_at")))
    expected = installation_plan(source_revision, plan.get("filesystem_uuid"), now=created)
    if (dict(plan) != expected or confirmation != expected["plan_sha256"]
            or not created <= current <= expiry):
        raise InventoryError("cache installation plan is expired, changed or cross-bound")
    # Never overwrite an existing accepted layout or consume the plan twice.
    if RECORD.exists() or RECORD.is_symlink():
        raise InventoryError("cache layout already exists; installation is not replayable")
    journal_path = RECORD.with_name("cache-installation.json")
    journal = None
    if journal_path.exists() or journal_path.is_symlink():
        journal = json.loads(_owned_bytes(journal_path))
        if journal.get("plan") != dict(plan) or journal.get("phase") not in {"PREPARED", "CREATED", "UNIT_INSTALLED", "MOUNTED"}:
            raise InventoryError("cache installation journal is unresolved or cross-bound")
    ops = NativeBtrfsOps("upd-20000101T000000Z-000000000000")
    try:
        identity = ops.root_identity()
        if identity.filesystem_uuid != plan["filesystem_uuid"]:
            raise InventoryError("cache installation root filesystem changed")
        ops._mount_top(identity)
        top_rows = json.loads(ops._run(("findmnt", "--json", "--mountpoint", str(ops.top),
                                       "--output", "TARGET,FSTYPE,FSROOT,UUID"), check=True).stdout).get("filesystems")
        top_row = top_rows[0] if isinstance(top_rows, list) and len(top_rows) == 1 else {}
        if (top_row.get("target") != str(ops.top) or top_row.get("fstype") != "btrfs"
                or top_row.get("fsroot") != "/" or top_row.get("uuid") != plan["filesystem_uuid"]):
            raise InventoryError("cache provisioning top-level mount identity is unresolved")
        destination = ops.top / SUBVOLUME
        # Revalidate these parents on restart too, before any creation or
        # mount-owner call. A durable journal does not bless changed ancestors.
        from maho_generation_gc import CertifiedFileGC
        guard = CertifiedFileGC(roots={"cache":CACHE.parent}, state_root=RECORD.parent)
        for parent in (ops.top, CACHE.parent, UNIT_PATH.parent, RECORD.parent):
            fd = guard._trusted_directory(parent); os.close(fd)
        if journal is None:
            for p in (destination, CACHE, UNIT_PATH):
                if p.exists() or p.is_symlink():
                    raise InventoryError("cache installation would replace unknown existing state")
            journal = {"plan": dict(plan), "phase": "PREPARED"}
            _atomic_json(journal_path, journal)
        if journal["phase"] == "PREPARED":
            if destination.exists() or destination.is_symlink() or CACHE.exists() or CACHE.is_symlink() or UNIT_PATH.exists() or UNIT_PATH.is_symlink():
                raise InventoryError("unrecorded cache creation requires independent reconciliation")
            ops._run(("btrfs", "subvolume", "create", str(destination)), check=True)
            os.chmod(destination, 0o755)
            subvolume_uuid = ops._show_uuid(destination)
            ops._run(("btrfs", "filesystem", "sync", str(ops.top)), check=True)
            journal.update(phase="CREATED", subvolume_uuid=subvolume_uuid)
            _atomic_json(journal_path, journal)
        if (destination.is_symlink() or ops._show_uuid(destination) != journal["subvolume_uuid"]
                or ops._read_only(destination)):
            raise InventoryError("cache installation subvolume identity drifted")
        if not CACHE.exists():
            CACHE.mkdir(mode=0o755)
            fd = os.open(CACHE.parent, os.O_RDONLY | os.O_DIRECTORY); os.fsync(fd); os.close(fd)
        if CACHE.is_symlink() or not CACHE.is_dir() or CACHE.stat().st_uid != 0 or CACHE.stat().st_mode & 0o022:
            raise InventoryError("cache mount target is unsafe")
        unit = mount_unit(plan["filesystem_uuid"]).encode()
        if UNIT_PATH.exists() or UNIT_PATH.is_symlink():
            if _owned_bytes(UNIT_PATH) != unit:
                raise InventoryError("cache mount unit differs from exact installation")
        else:
            fd = os.open(UNIT_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, "wb") as stream:
                stream.write(unit); stream.flush(); os.fsync(stream.fileno())
            fd = os.open(UNIT_PATH.parent, os.O_RDONLY | os.O_DIRECTORY); os.fsync(fd); os.close(fd)
        journal["phase"] = "UNIT_INSTALLED"; _atomic_json(journal_path, journal)
        # Verify any pre-existing mount before invoking the mount owner.
        mounted = ops._run(("mountpoint", "-q", str(CACHE))).returncode == 0
        if mounted:
            shown = ops._show_uuid(CACHE)
            if shown != journal["subvolume_uuid"]:
                raise InventoryError("cache installation mount was substituted")
        elif any(CACHE.iterdir()):
            raise InventoryError("cache mount would hide unknown files")
        ops._run(("systemctl", "daemon-reload"), check=True)
        ops._run(("systemctl", "enable", "--now", UNIT_NAME), check=True)
        journal["phase"] = "MOUNTED"; _atomic_json(journal_path, journal)
        record = {"kind":"maho-isolated-update-cache", "schema_version":1, "phase":"COMMITTED",
                  "source_revision":source_revision, "filesystem_uuid":plan["filesystem_uuid"],
                  "subvolume_uuid":journal["subvolume_uuid"], "subvolume":SUBVOLUME, "path":str(CACHE),
                  "mount_unit_sha256":plan["mount_unit_sha256"], "installation_plan_sha256":plan["plan_sha256"]}
        record["layout_sha256"] = digest_payload(record)
        validate_layout(record, unit_bytes=unit, observed_uid=CACHE.stat().st_uid, observed_mode=CACHE.stat().st_mode)
        for lane in LEGACY_ROOTS:
            target = CACHE / lane
            target.mkdir(mode=0o755, exist_ok=True)
            if target.is_symlink() or not target.is_dir() or target.stat().st_uid != 0 or target.stat().st_mode & 0o022:
                raise InventoryError("cache installation lane is unsafe")
        fd = os.open(CACHE, os.O_RDONLY | os.O_DIRECTORY); os.fsync(fd); os.close(fd)
        _atomic_json(RECORD, record)
        journal["phase"] = "COMMITTED"; _atomic_json(journal_path, journal)
        return record
    finally:
        ops.close()
