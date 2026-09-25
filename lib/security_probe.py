#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import shlex
import stat
import sys
import uuid
from pathlib import Path

from maho_live_generation import read_live_publication
from maho_persistence_transition import build_transition_plan
from maho_runtime_release import verify_release
from maho_update_state import read_transaction, transaction_path

VERSION = 1
NAME_RE = re.compile(r"^[A-Za-z0-9@._+:-]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MTREE_ESCAPE_RE = re.compile(r"\\([0-7]{3})")
CRITICAL_PREFIXES = (
    "bin/",
    "sbin/",
    "usr/bin/",
    "usr/sbin/",
    "usr/lib/systemd/system/",
    "usr/lib/systemd/user/",
    "usr/lib/security/",
)
STARTUP_FILES = (
    ".profile",
    ".bash_profile",
    ".bash_login",
    ".zprofile",
    ".zlogin",
)
MAHO_EXPECTED_DEFAULT_USER_UNITS = frozenset({
    "maho-observe.service",
    "maho-security.service",
    "maho-guardian.service",
    "maho-kbdlight.service",
})


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def secure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def atomic_private(path: Path, data: bytes) -> None:
    secure_dir(path.parent)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        offset = 0
        while offset < len(data):
            offset += os.write(fd, data[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def parse_sections(path: Path) -> dict[str, list[str]]:
    lines = path.read_text(errors="replace").splitlines()
    sections: dict[str, list[str]] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("%") and line.endswith("%"):
            key = line.strip("%")
            i += 1
            values: list[str] = []
            while i < len(lines) and lines[i] != "":
                values.append(lines[i])
                i += 1
            sections[key] = values
        i += 1
    return sections


def first(sections: dict[str, list[str]], key: str, default=None):
    values = sections.get(key) or []
    return values[0] if values else default


def package_records(db_root: Path) -> list[dict]:
    if not db_root.is_dir():
        return []
    records = []
    for desc in sorted(db_root.glob("*/desc")):
        try:
            sections = parse_sections(desc)
            files_path = desc.parent / "files"
            package_files = (
                parse_sections(files_path).get("FILES", [])
                if files_path.is_file()
                else sections.get("FILES", [])
            )
        except OSError:
            continue
        name = first(sections, "NAME")
        version = first(sections, "VERSION")
        if not name or not version:
            continue
        records.append(
            {
                "name": name,
                "version": version,
                "install_date": first(sections, "INSTALLDATE"),
                "dir": desc.parent,
                "files": package_files,
            }
        )
    return records


def package_record(db_root: Path, name: str) -> dict | None:
    for record in package_records(db_root):
        if record["name"] == name:
            return record
    return None


def decode_mtree_path(value: str) -> str:
    def repl(match: re.Match) -> str:
        return chr(int(match.group(1), 8))

    value = MTREE_ESCAPE_RE.sub(repl, value)
    if value.startswith("./"):
        value = value[2:]
    return value.lstrip("/")


def parse_mtree(path: Path):
    try:
        raw = gzip.open(path, "rt", errors="replace")
    except (OSError, gzip.BadGzipFile):
        return
    defaults: dict[str, str] = {}
    try:
        for line in raw:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Pacman mtree encodes whitespace and special path bytes as octal
            # escapes. Plain splitting preserves those backslashes until
            # decode_mtree_path() handles them; POSIX shlex would consume them.
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "/set":
                for token in parts[1:]:
                    if "=" in token:
                        key, value = token.split("=", 1)
                        defaults[key] = value
                continue
            if parts[0] == "/unset":
                for key in parts[1:]:
                    defaults.pop(key, None)
                continue
            rel = decode_mtree_path(parts[0])
            attrs = dict(defaults)
            for token in parts[1:]:
                if "=" not in token:
                    continue
                key, value = token.split("=", 1)
                attrs[key] = value
            yield rel, attrs
    finally:
        raw.close()


def in_critical_scope(rel: str) -> bool:
    if rel in {"usr/lib/ld-linux-x86-64.so.2", "usr/lib/ld-linux.so.2"}:
        return True
    return any(rel.startswith(prefix) for prefix in CRITICAL_PREFIXES)


def integrity_scan(args) -> dict:
    db_root = Path(args.db_root)
    fs_root = Path(args.fs_root)
    records = package_records(db_root)
    if args.package:
        records = [r for r in records if r["name"] == args.package]
        if not records:
            return {
                "version": VERSION,
                "kind": "package-file-integrity",
                "result": "package-not-installed",
                "package": args.package,
                "scope": "package",
                "checked": 0,
                "packages": 0,
                "modified": [],
                "missing": [],
                "type_changed": [],
                "unreadable": [],
            }

    modified = []
    missing = []
    type_changed = []
    unreadable = []
    checked = 0
    mtree_packages = 0
    expected = 0

    def append_limited(bucket: list, item: dict) -> None:
        if len(bucket) < args.max_findings:
            bucket.append(item)

    for record in records:
        mtree = record["dir"] / "mtree"
        if not mtree.is_file():
            continue
        entries = parse_mtree(mtree)
        if entries is None:
            continue
        mtree_packages += 1
        for rel, attrs in entries:
            if attrs.get("type") != "file":
                continue
            digest = attrs.get("sha256digest")
            if not digest or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
                continue
            if not args.package and args.scope == "critical" and not in_critical_scope(rel):
                continue
            expected += 1
            target = fs_root / rel
            item = {"package": record["name"], "version": record["version"], "path": "/" + rel}
            try:
                st = target.lstat()
            except FileNotFoundError:
                append_limited(missing, item)
                continue
            except PermissionError:
                append_limited(unreadable, item | {"reason": "stat-denied"})
                continue
            if not stat.S_ISREG(st.st_mode):
                append_limited(type_changed, item | {"actual_type": "symlink" if stat.S_ISLNK(st.st_mode) else "other"})
                continue
            try:
                h = hashlib.sha256()
                with target.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        h.update(chunk)
                actual = h.hexdigest()
            except (PermissionError, OSError) as exc:
                append_limited(unreadable, item | {"reason": type(exc).__name__})
                continue
            checked += 1
            if actual.lower() != digest.lower():
                append_limited(modified, item | {"expected_sha256": digest.lower(), "actual_sha256": actual})

    changes = len(modified) + len(missing) + len(type_changed)
    if mtree_packages == 0 or expected == 0:
        result = "unavailable"
    elif changes:
        result = "changed"
    elif unreadable:
        result = "partial"
    else:
        result = "clean"

    return {
        "version": VERSION,
        "kind": "package-file-integrity",
        "result": result,
        "scope": "package" if args.package else args.scope,
        "package": args.package,
        "packages": mtree_packages,
        "expected": expected,
        "checked": checked,
        "modified": modified,
        "missing": missing,
        "type_changed": type_changed,
        "unreadable": unreadable,
        "truncated": any(len(x) >= args.max_findings for x in (modified, missing, type_changed, unreadable)),
        "trust_note": "Compared current files with local pacman mtree metadata; this is evidence, not an independent trust anchor.",
    }


def normalized_package_paths(record: dict) -> set[str]:
    paths = set()
    for value in record.get("files", []):
        value = value.strip().lstrip("/")
        if value and not value.endswith("/"):
            paths.add(value)
    return paths


def exe_to_rel(exe: str, fs_root: Path) -> tuple[str | None, bool]:
    deleted = exe.endswith(" (deleted)")
    clean = exe[:-10] if deleted else exe
    if not clean.startswith("/"):
        return None, deleted
    try:
        rel = Path(clean).relative_to(fs_root) if fs_root != Path("/") else Path(clean).relative_to("/")
    except ValueError:
        return None, deleted
    return str(rel), deleted


def read_process(proc: Path, fs_root: Path) -> dict | None:
    try:
        exe = os.readlink(proc / "exe")
    except OSError:
        return None
    rel, deleted = exe_to_rel(exe, fs_root)
    status = {}
    try:
        for line in (proc / "status").read_text(errors="replace").splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                status[key] = value.strip()
    except OSError:
        pass
    try:
        cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        cmdline = ""
    uid = None
    uid_raw = status.get("Uid", "").split()
    if uid_raw and uid_raw[0].isdigit():
        uid = int(uid_raw[0])
    return {
        "pid": int(proc.name),
        "uid": uid,
        "name": status.get("Name") or proc.name,
        "exe": exe,
        "relative_exe": rel,
        "deleted": deleted,
        "cmdline": cmdline[:2048],
        "state": status.get("State"),
    }


def enabled_unit_refs(record: dict, fs_root: Path, home: Path, xdg_config: Path) -> list[dict]:
    package_paths = normalized_package_paths(record)
    unit_paths = {
        p for p in package_paths
        if p.startswith("usr/lib/systemd/system/") or p.startswith("usr/lib/systemd/user/")
    }
    if not unit_paths:
        return []
    roots = [fs_root / "etc/systemd/system", fs_root / "etc/systemd/user", xdg_config / "systemd/user"]
    rows = []
    seen = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_symlink():
                continue
            try:
                target = path.resolve(strict=False)
            except OSError:
                continue
            rel, _ = exe_to_rel(str(target), fs_root)
            if rel not in unit_paths:
                continue
            key = (str(path), rel)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"link": str(path), "unit_file": "/" + rel})
    return sorted(rows, key=lambda x: (x["link"], x["unit_file"]))


def package_impact(args) -> dict:
    db_root = Path(args.db_root)
    proc_root = Path(args.proc_root)
    fs_root = Path(args.fs_root)
    home = Path(args.home)
    xdg_config = Path(args.xdg_config)
    record = package_record(db_root, args.package)
    if not record:
        return {
            "version": VERSION,
            "kind": "package-impact",
            "package": args.package,
            "installed": False,
            "installed_version": None,
            "version_matches": None,
            "running_processes": [],
            "enabled_units": [],
            "package_file_count": 0,
        }

    package_paths = normalized_package_paths(record)
    processes = []
    if proc_root.is_dir():
        for proc in sorted(proc_root.iterdir(), key=lambda p: int(p.name) if p.name.isdigit() else 10**18):
            if not proc.name.isdigit() or not proc.is_dir():
                continue
            item = read_process(proc, fs_root)
            if item and item["relative_exe"] in package_paths:
                processes.append(item)

    return {
        "version": VERSION,
        "kind": "package-impact",
        "package": args.package,
        "installed": True,
        "installed_version": record["version"],
        "version_matches": (record["version"] == args.version) if args.version else None,
        "install_date": record.get("install_date"),
        "package_file_count": len(package_paths),
        "running_processes": processes,
        "enabled_units": enabled_unit_refs(record, fs_root, home, xdg_config),
    }


def runtime_scan(args) -> dict:
    proc_root = Path(args.proc_root)
    fs_root = Path(args.fs_root)
    current_uid = args.uid
    observations = []
    if proc_root.is_dir():
        for proc in proc_root.iterdir():
            if not proc.name.isdigit() or not proc.is_dir():
                continue
            item = read_process(proc, fs_root)
            if not item:
                continue
            if current_uid is not None and item["uid"] not in {current_uid, None}:
                continue
            exe = item["exe"]
            rel = item["relative_exe"] or ""
            signals = []
            risk = "low"
            if item["deleted"]:
                signals.append("deleted-executable")
                risk = "medium"
            if rel.startswith(("tmp/", "var/tmp/", "dev/shm/")):
                signals.append("temporary-filesystem-executable")
                risk = "medium"
            if "memfd:" in exe:
                signals.append("memfd-executable")
                risk = "medium"
            if signals:
                observations.append(item | {"signals": signals, "risk": risk})
    observations.sort(key=lambda x: (x["risk"], x["pid"]))
    return {
        "version": VERSION,
        "kind": "runtime-executable-observations",
        "result": "observed" if observations else "clean",
        "observations": observations,
        "trust_note": "Runtime heuristics are evidence only; deleted or temporary executables can have legitimate causes.",
    }


def persistence_inventory(home: Path, xdg_config: Path, fs_root: Path) -> dict:
    items = []
    seen = set()

    def add(path: Path, kind: str) -> None:
        try:
            key = str(path)
            if key in seen:
                return
            seen.add(key)
            if path.is_symlink():
                target = os.readlink(path)
                row = {"path": key, "kind": kind, "type": "symlink", "target": target}
            elif path.is_file():
                try:
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                except (PermissionError, OSError):
                    digest = None
                row = {"path": key, "kind": kind, "type": "file", "sha256": digest}
            else:
                return
            items.append(row)
        except OSError:
            return

    roots = [
        (fs_root / "etc/systemd/system", "systemd-system"),
        (fs_root / "etc/systemd/user", "systemd-user-system"),
        (xdg_config / "systemd/user", "systemd-user"),
    ]
    for root, kind in roots:
        if root.is_dir():
            for path in root.rglob("*"):
                if path.is_symlink() or (path.is_file() and path.suffix in {".service", ".timer", ".socket", ".path"}):
                    add(path, kind)

    for root, kind in (
        (fs_root / "etc/xdg/autostart", "xdg-autostart-system"),
        (xdg_config / "autostart", "xdg-autostart-user"),
    ):
        if root.is_dir():
            for path in root.glob("*.desktop"):
                add(path, kind)

    for name in STARTUP_FILES:
        add(home / name, "shell-login")

    items.sort(key=lambda x: (x["kind"], x["path"]))
    return {"version": VERSION, "kind": "persistence-inventory", "items": items}


def _verified_maho_user_wiring(item: dict, home: Path, xdg_config: Path) -> dict | None:
    """Recognize exact user-unit state expected by the verified Maho runtime.

    This proves the resulting state matches Maho's declared wiring policy. It
    deliberately does not claim to identify which process created the link.
    """
    if item.get("type") != "symlink":
        return None
    raw_path = item.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        return None
    path = Path(raw_path)
    unit_root = xdg_config / "systemd/user"

    direct_unit = path.parent == unit_root
    wants_unit = (
        path.parent.parent == unit_root
        and path.parent.name.endswith(".wants")
    )
    if not (direct_unit or wants_unit):
        return None
    if path.suffix not in {".service", ".timer", ".socket", ".path", ".target"}:
        return None

    # Installation of the unit file itself is expected for any unit actually
    # shipped by the verified runtime. Automatic startup is stricter: only the
    # core units declared for default.target are expected.
    if wants_unit:
        if path.parent.name != "default.target.wants":
            return None
        if path.name not in MAHO_EXPECTED_DEFAULT_USER_UNITS:
            return None

    data_home = Path(os.environ.get("XDG_DATA_HOME") or (home / ".local/share"))
    runtime_root = data_home / "maho/runtime"
    current = runtime_root / "current"
    releases = runtime_root / "releases"
    verification = verify_release(current, releases)
    if not verification.verified:
        return None

    release = Path(verification.path)
    expected = release / "systemd/user" / path.name
    try:
        observed = path.resolve(strict=True)
        expected_real = expected.resolve(strict=True)
    except OSError:
        return None
    if observed != expected_real:
        return None

    classification = "expected-maho-unit" if direct_unit else "expected-maho-enable"
    reason = (
        "unit resolves exactly to the verified current Maho runtime"
        if direct_unit
        else "default-target enablement matches Maho's expected core-service policy"
    )
    return {
        "owner": "maho-runtime",
        "classification": classification,
        "reason": reason,
        "runtime": str(release),
        "content_sha256": verification.content_sha256,
        "source_revision": verification.source_revision,
    }


def _install_script_enables_unit(path: Path, unit: str) -> bool:
    """Return true only for a literal, non-shell-expanded systemctl enable."""
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return False
    accepted = {unit, Path(unit).stem}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.endswith("\\"):
            continue
        try:
            tokens = shlex.split(stripped, comments=True, posix=True)
        except ValueError:
            continue
        if len(tokens) < 3 or Path(tokens[0]).name != "systemctl" or tokens[1] != "enable":
            continue
        arguments = tokens[2:]
        if any(any(mark in token for mark in ("$", "`", ";", "&", "|")) for token in arguments):
            continue
        if accepted.intersection(token for token in arguments if not token.startswith("-")):
            return True
    return False


def _verified_package_system_wiring(item: dict, db_root: Path, fs_root: Path) -> dict | None:
    """Recognize exact system-unit enablement declared by an installed package.

    Package ownership by itself is not enough. The link must target an intact
    package-owned unit and the package install script must literally enable it.
    """
    if item.get("type") != "symlink" or item.get("kind") != "systemd-system":
        return None
    raw_path = item.get("path")
    target = item.get("target")
    if not isinstance(raw_path, str) or not isinstance(target, str):
        return None
    path = Path(raw_path)
    try:
        rel = path.relative_to(fs_root / "etc/systemd/system")
    except ValueError:
        return None
    if len(rel.parts) != 2 or not rel.parts[0].endswith((".wants", ".requires")):
        return None
    unit = rel.name
    if Path(target) != Path("/usr/lib/systemd/system") / unit:
        return None
    unit_rel = f"usr/lib/systemd/system/{unit}"
    unit_path = fs_root / unit_rel
    if not unit_path.is_file() or unit_path.is_symlink():
        return None

    for record in package_records(db_root):
        mtree = record["dir"] / "mtree"
        entry = next(((relpath, attrs) for relpath, attrs in (parse_mtree(mtree) or ()) if relpath == unit_rel), None)
        if entry is None:
            continue
        digest = entry[1].get("sha256digest")
        if not digest:
            continue
        try:
            observed = hashlib.sha256(unit_path.read_bytes()).hexdigest()
        except OSError:
            continue
        if observed != digest:
            continue
        install_script = record["dir"] / "install"
        if not _install_script_enables_unit(install_script, unit):
            continue
        return {
            "owner": record["name"],
            "owner_version": record["version"],
            "classification": "expected-package-enable",
            "reason": "link targets an intact package-owned unit explicitly enabled by the package install script",
            "unit": unit,
            "unit_sha256": observed,
        }
    return None


def _persistence_attribution(item: dict, home: Path, xdg_config: Path, db_root: Path, fs_root: Path) -> dict | None:
    return (
        _verified_maho_user_wiring(item, home, xdg_config)
        or _verified_package_system_wiring(item, db_root, fs_root)
    )


def _annotate_persistence_change(item: dict, home: Path, xdg_config: Path, db_root: Path, fs_root: Path) -> dict:
    row = dict(item)
    attribution = _persistence_attribution(row, home, xdg_config, db_root, fs_root)
    if attribution is not None:
        row["expected"] = True
        row["attribution"] = attribution
    return row


def validate_persistence_snapshot(data: dict) -> None:
    if data.get("version") != VERSION or data.get("kind") != "persistence-snapshot":
        raise SystemExit("unsupported persistence snapshot")
    inventory = data.get("inventory")
    if not isinstance(inventory, dict) or inventory.get("kind") != "persistence-inventory":
        raise SystemExit("invalid persistence inventory")
    if not isinstance(inventory.get("items"), list):
        raise SystemExit("invalid persistence item list")
    state = data.get("state_sha256")
    if not isinstance(state, str) or not SHA256_RE.fullmatch(state) or state != stable_hash(inventory):
        raise SystemExit("persistence snapshot state hash does not match inventory")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def validate_authority_source_file(path: Path, *, require_root: bool) -> bytes:
    try:
        info = path.lstat()
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"authority source is unreadable: {path}") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise ValueError(f"authority source is not a regular file: {path}")
    if info.st_mode & 0o022:
        raise ValueError(f"authority source is writable by group or others: {path}")
    if require_root and info.st_uid != 0:
        raise ValueError(f"system authority source is not root-owned: {path}")
    return data


def validate_persistence_authority(baseline_data: dict, authority: dict) -> None:
    kind = authority.get("kind")
    if authority.get("version") != VERSION or kind not in {
        "persistence-baseline-authority",
        "persistence-baseline-transition-authority",
    }:
        raise ValueError("unsupported persistence baseline authority")
    expected_scope = (
        "exact-persistence-state"
        if kind == "persistence-baseline-authority"
        else "exact-package-owned-transition"
    )
    if authority.get("authority_scope") != expected_scope:
        raise ValueError("persistence baseline authority scope is invalid")
    authority_id = authority.get("authority_id")
    prefix = "pba-" if kind == "persistence-baseline-authority" else "pbt-"
    if not isinstance(authority_id, str) or not authority_id.startswith(prefix):
        raise ValueError("persistence baseline authority identity is invalid")
    accepted_state = authority.get("accepted_state_sha256")
    if not isinstance(accepted_state, str) or not SHA256_RE.fullmatch(accepted_state):
        raise ValueError("persistence baseline authority state is invalid")
    if accepted_state != baseline_data.get("state_sha256"):
        raise ValueError("persistence baseline authority does not bind this state")
    if baseline_data.get("baseline_authority_id") != authority_id:
        raise ValueError("persistence baseline authority identity does not match baseline")
    expected_authority_hash = baseline_data.get("baseline_authority_sha256")
    actual_authority_hash = stable_hash(authority)
    if not isinstance(expected_authority_hash, str) or expected_authority_hash != actual_authority_hash:
        raise ValueError("persistence baseline authority receipt hash mismatch")
    if kind == "persistence-baseline-authority":
        source_digest = authority.get("source_snapshot_sha256")
        if not isinstance(source_digest, str) or not SHA256_RE.fullmatch(source_digest):
            raise ValueError("persistence baseline authority source digest is invalid")
        reason = authority.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("persistence baseline authority reason is missing")
    else:
        if authority.get("previous_baseline_state_sha256") == accepted_state:
            raise ValueError("persistence transition did not advance the baseline")
        for key in (
            "plan_sha256", "transaction_sha256", "publication_sha256",
            "previous_baseline_state_sha256",
        ):
            if not isinstance(authority.get(key), str) or SHA256_RE.fullmatch(authority[key]) is None:
                raise ValueError(f"persistence transition authority {key} is invalid")
        if not isinstance(authority.get("changes"), list) or not authority["changes"]:
            raise ValueError("persistence transition authority has no exact changes")


def load_persistence_authority(baseline_data: dict, authorities: Path) -> tuple[dict, Path]:
    authority_id = baseline_data.get("baseline_authority_id")
    if not isinstance(authority_id, str) or not re.fullmatch(r"pb[at]-[0-9a-f]{16}-[0-9a-f]{12}", authority_id):
        raise ValueError("persistence baseline does not reference a valid authority identity")
    path = authorities / f"{authority_id}.json"
    authority = load_json(path)
    validate_persistence_authority(baseline_data, authority)
    return authority, path


def persistence_command(args) -> dict:
    state_root = Path(args.state_root) / "persistence"
    snapshots = state_root / "snapshots"
    latest = state_root / "latest.json"
    baseline = state_root / "baseline.json"
    authorities = state_root / "authorities"
    home = Path(args.home)
    xdg_config = Path(args.xdg_config)
    fs_root = Path(args.fs_root)
    db_root = Path(args.db_root)

    if args.persistence_command == "snapshot":
        inventory = persistence_inventory(home, xdg_config, fs_root)
        snapshot = {
            "version": VERSION,
            "kind": "persistence-snapshot",
            "captured_at": now_utc(),
            "inventory": inventory,
            "state_sha256": stable_hash(inventory),
        }
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = snapshots / f"{stamp}-{uuid.uuid4().hex[:8]}.json"
        data = canonical_bytes(snapshot)
        atomic_private(path, data)
        atomic_private(latest, data)
        return {"result": "snapshot", "path": str(path), "items": len(inventory["items"]), "state_sha256": snapshot["state_sha256"]}

    if args.persistence_command == "baseline-set":
        if args.source == "latest":
            source = latest.resolve()
        else:
            source = Path(args.source).expanduser().resolve()
            try:
                source.relative_to(snapshots.resolve())
            except ValueError:
                raise SystemExit("persistence baseline source must be a Maho persistence snapshot or 'latest'")
        if not source.is_file():
            raise SystemExit(f"persistence snapshot does not exist: {source}")
        data = load_json(source)
        validate_persistence_snapshot(data)
        accepted_state = str(args.accept_state or "")
        if not SHA256_RE.fullmatch(accepted_state):
            raise SystemExit("baseline-set requires --accept-state with the exact 64-hex snapshot state")
        if accepted_state != data.get("state_sha256"):
            raise SystemExit("accepted persistence state does not match the selected snapshot")
        reason = str(args.reason or "").strip()
        if not reason or len(reason) > 500:
            raise SystemExit("baseline-set requires a non-empty --reason of at most 500 characters")

        current_inventory = persistence_inventory(home, xdg_config, fs_root)
        current_state = stable_hash(current_inventory)
        if current_state != accepted_state:
            raise SystemExit("selected persistence snapshot is stale; capture and inspect a new snapshot before acceptance")

        previous_state = None
        if baseline.is_file():
            try:
                previous = load_json(baseline)
                validate_persistence_snapshot(previous)
                previous_state = previous.get("state_sha256")
            except (OSError, ValueError, json.JSONDecodeError, SystemExit):
                previous_state = None

        accepted_at = now_utc()
        authority_id = f"pba-{accepted_state[:16]}-{uuid.uuid4().hex[:12]}"
        authority = {
            "version": VERSION,
            "kind": "persistence-baseline-authority",
            "authority_id": authority_id,
            "authority_scope": "exact-persistence-state",
            "accepted_at": accepted_at,
            "accepted_by_uid": os.getuid(),
            "accepted_state_sha256": accepted_state,
            "source_snapshot": str(source),
            "source_snapshot_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "previous_baseline_state_sha256": previous_state,
            "items": len(data["inventory"]["items"]),
            "reason": reason,
        }
        authority_sha256 = stable_hash(authority)
        baseline_data = dict(data)
        baseline_data["baseline_authority_id"] = authority_id
        baseline_data["baseline_authority_sha256"] = authority_sha256

        authority_history = authorities / f"{authority_id}.json"
        atomic_private(authority_history, canonical_bytes(authority))
        atomic_private(baseline, canonical_bytes(baseline_data))
        return {
            "result": "baseline-set",
            "path": str(baseline),
            "source": str(source),
            "items": len(data["inventory"]["items"]),
            "state_sha256": accepted_state,
            "authority_id": authority_id,
            "authority_sha256": authority_sha256,
            "authority_path": str(authority_history),
            "accepted_at": accepted_at,
            "reason": reason,
            "previous_baseline_state_sha256": previous_state,
        }

    if args.persistence_command == "baseline-transition":
        transaction_id = str(args.source or "")
        update_root = Path(args.update_root)
        generation_root = Path(args.generation_root)
        require_system_update_owner = update_root == Path("/var/lib/maho/update")
        require_system_generation_owner = generation_root == Path("/var/lib/maho/generations")
        current_path = update_root / "current"
        current_raw = validate_authority_source_file(
            current_path, require_root=require_system_update_owner,
        ).decode(errors="strict").strip()
        if current_raw != transaction_id:
            raise SystemExit("baseline transition requires the exact current update transaction")
        try:
            tx_path = transaction_path(update_root, transaction_id)
            tx_raw = validate_authority_source_file(
                tx_path, require_root=require_system_update_owner,
            )
            transaction = read_transaction(tx_path)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise SystemExit(f"update transaction authority is invalid: {exc}") from exc

        publication_path = generation_root / "live.json"
        try:
            publication_raw = validate_authority_source_file(
                publication_path, require_root=require_system_generation_owner,
            )
            publication = read_live_publication(generation_root)
        except ValueError as exc:
            raise SystemExit(f"current generation authority is invalid: {exc}") from exc
        if publication is None:
            raise SystemExit("current generation authority does not verify")
        if not baseline.is_file():
            raise SystemExit("baseline transition requires an existing trusted persistence baseline")
        baseline_data = load_json(baseline)
        validate_persistence_snapshot(baseline_data)
        try:
            previous_authority, _ = load_persistence_authority(baseline_data, authorities)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise SystemExit(f"existing persistence baseline authority is invalid: {exc}") from exc

        original_command = args.persistence_command
        args.persistence_command = "check"
        try:
            check = persistence_command(args)
        finally:
            args.persistence_command = original_command
        try:
            plan = build_transition_plan(
                baseline=baseline_data,
                check=check,
                transaction=transaction,
                publication=publication,
                db_root=db_root,
                fs_root=fs_root,
                transaction_sha256=hashlib.sha256(tx_raw).hexdigest(),
                publication_sha256=hashlib.sha256(publication_raw).hexdigest(),
            )
        except ValueError as exc:
            raise SystemExit(f"persistence baseline transition denied: {exc}") from exc

        public_plan = {key: value for key, value in plan.items() if key != "target_inventory"}
        if not args.apply:
            return {
                "result": "baseline-transition-ready",
                "baseline": str(baseline),
                "previous_authority_id": previous_authority["authority_id"],
                **public_plan,
            }
        accepted_state = str(args.accept_state or "")
        if accepted_state != plan["target_state_sha256"]:
            raise SystemExit("baseline transition --accept-state must equal the exact planned target state")

        accepted_at = now_utc()
        authority_id = f"pbt-{accepted_state[:16]}-{uuid.uuid4().hex[:12]}"
        authority = {
            "version": VERSION,
            "kind": "persistence-baseline-transition-authority",
            "authority_id": authority_id,
            "authority_scope": "exact-package-owned-transition",
            "accepted_at": accepted_at,
            "accepted_by_uid": os.getuid(),
            "accepted_state_sha256": accepted_state,
            "previous_baseline_authority_id": previous_authority["authority_id"],
            **public_plan,
        }
        authority_sha256 = stable_hash(authority)
        replacement = {
            "version": VERSION,
            "kind": "persistence-snapshot",
            "captured_at": accepted_at,
            "inventory": plan["target_inventory"],
            "state_sha256": accepted_state,
            "baseline_authority_id": authority_id,
            "baseline_authority_sha256": authority_sha256,
        }
        authority_path = authorities / f"{authority_id}.json"
        atomic_private(authority_path, canonical_bytes(authority))
        atomic_private(baseline, canonical_bytes(replacement))
        return {
            "result": "baseline-transition-applied",
            "path": str(baseline),
            "authority_id": authority_id,
            "authority_path": str(authority_path),
            "authority_sha256": authority_sha256,
            "accepted_at": accepted_at,
            **public_plan,
        }

    if args.persistence_command == "baseline-show":
        if not baseline.is_file():
            return {"result": "no-baseline", "path": str(baseline)}
        data = load_json(baseline)
        validate_persistence_snapshot(data)
        try:
            authority, authority_path = load_persistence_authority(data, authorities)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {
                "result": "baseline-untrusted",
                "path": str(baseline),
                "state_sha256": data.get("state_sha256"),
                "reason": str(exc),
            }
        return {
            "result": "baseline",
            "path": str(baseline),
            "captured_at": data.get("captured_at"),
            "items": len(data["inventory"]["items"]),
            "state_sha256": data["state_sha256"],
            "authority_id": authority["authority_id"],
            "authority_kind": authority["kind"],
            "accepted_at": authority["accepted_at"],
            "authority_reason": authority.get("reason") or (
                f"verified package transition {authority.get('transaction_id')}"
            ),
            "authority_path": str(authority_path),
        }

    if args.persistence_command == "baseline-clear":
        baseline.unlink(missing_ok=True)
        retained = len(list(authorities.glob("*.json"))) if authorities.is_dir() else 0
        return {"result": "baseline-cleared", "path": str(baseline), "retained_authorities": retained}

    if args.persistence_command == "check":
        if not baseline.is_file():
            return {"result": "no-baseline", "path": str(baseline)}
        base = load_json(baseline)
        validate_persistence_snapshot(base)
        try:
            authority, authority_path = load_persistence_authority(base, authorities)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {
                "result": "unavailable",
                "reason": "baseline-authority-invalid",
                "detail": str(exc),
                "baseline": str(baseline),
                "baseline_state_sha256": base.get("state_sha256"),
            }
        current_inventory = persistence_inventory(home, xdg_config, fs_root)
        before = {x["path"]: x for x in base["inventory"]["items"]}
        after = {x["path"]: x for x in current_inventory["items"]}
        added = [
            _annotate_persistence_change(after[p], home, xdg_config, db_root, fs_root)
            for p in sorted(set(after) - set(before))
        ]
        removed = [before[p] for p in sorted(set(before) - set(after))]
        changed = []
        for p in sorted(set(before) & set(after)):
            if before[p] == after[p]:
                continue
            row = {"path": p, "before": before[p], "after": after[p]}
            attribution = _persistence_attribution(after[p], home, xdg_config, db_root, fs_root)
            if attribution is not None:
                row["expected"] = True
                row["attribution"] = attribution
            changed.append(row)

        unexpected_added = [item for item in added if item.get("expected") is not True]
        unexpected_changed = [item for item in changed if item.get("expected") is not True]
        unexpected_removed = list(removed)
        expected_changes = [
            {"change": "added", **item} for item in added if item.get("expected") is True
        ] + [
            {"change": "changed", **item} for item in changed if item.get("expected") is True
        ]
        result = "clean" if not (added or removed or changed) else "changed"
        attention_result = "clean" if not (unexpected_added or unexpected_removed or unexpected_changed) else "changed"
        return {
            "result": result,
            "attention_result": attention_result,
            "baseline": str(baseline),
            "baseline_state_sha256": base["state_sha256"],
            "baseline_authority_id": authority["authority_id"],
            "baseline_authority_path": str(authority_path),
            "current_state_sha256": stable_hash(current_inventory),
            "added": added,
            "removed": removed,
            "changed": changed,
            "expected_changes": expected_changes,
            "unexpected_added": unexpected_added,
            "unexpected_removed": unexpected_removed,
            "unexpected_changed": unexpected_changed,
        }

    raise SystemExit("unknown persistence command")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="security_probe.py")
    sub = parser.add_subparsers(dest="command", required=True)

    integ = sub.add_parser("integrity")
    integ.add_argument("--db-root", required=True)
    integ.add_argument("--fs-root", default="/")
    integ.add_argument("--scope", choices=("critical", "full"), default="critical")
    integ.add_argument("--package")
    integ.add_argument("--max-findings", type=int, default=200)

    impact = sub.add_parser("impact")
    impact.add_argument("package")
    impact.add_argument("--version")
    impact.add_argument("--db-root", required=True)
    impact.add_argument("--proc-root", default="/proc")
    impact.add_argument("--fs-root", default="/")
    impact.add_argument("--home", required=True)
    impact.add_argument("--xdg-config", required=True)

    runtime = sub.add_parser("runtime")
    runtime.add_argument("--proc-root", default="/proc")
    runtime.add_argument("--fs-root", default="/")
    runtime.add_argument("--uid", type=int)

    persist = sub.add_parser("persistence")
    persist.add_argument("persistence_command", choices=("snapshot", "baseline-set", "baseline-transition", "baseline-show", "baseline-clear", "check"))
    persist.add_argument("source", nargs="?")
    persist.add_argument("--accept-state")
    persist.add_argument("--reason")
    persist.add_argument("--apply", action="store_true")
    persist.add_argument("--update-root", default="/var/lib/maho/update")
    persist.add_argument("--generation-root", default="/var/lib/maho/generations")
    persist.add_argument("--state-root", required=True)
    persist.add_argument("--home", required=True)
    persist.add_argument("--xdg-config", required=True)
    persist.add_argument("--fs-root", default="/")
    persist.add_argument("--db-root", default="/var/lib/pacman/local")

    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "integrity":
        result = integrity_scan(args)
    elif args.command == "impact":
        if not NAME_RE.fullmatch(args.package):
            raise SystemExit("invalid package name")
        result = package_impact(args)
    elif args.command == "runtime":
        result = runtime_scan(args)
    elif args.command == "persistence":
        if args.persistence_command == "baseline-set":
            if not args.source:
                raise SystemExit("baseline-set requires SNAPSHOT or latest")
            if not args.accept_state:
                raise SystemExit("baseline-set requires --accept-state STATE_SHA256")
            if not args.reason:
                raise SystemExit("baseline-set requires --reason TEXT")
        if args.persistence_command == "baseline-transition" and not args.source:
            raise SystemExit("baseline-transition requires TRANSACTION_ID")
        result = persistence_command(args)
    else:
        raise SystemExit("unknown command")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
