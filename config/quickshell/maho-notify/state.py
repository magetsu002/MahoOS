#!/usr/bin/env python3

"""Private, bounded state storage for Maho Notify.

The line-oriented ``serve`` mode keeps notification content on stdin/stdout
between Quickshell and this helper. Content is never placed in argv or logs.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


VERSION = 2
STATUS_VERSION = 1
MAX_ENTRIES = 500
MAX_AGE_SECONDS = 7 * 24 * 60 * 60
ALLOWED_FIELDS = {
    "id",
    "protocolId",
    "appKey",
    "appName",
    "summary",
    "body",
    "urgency",
    "timestamp",
    "read",
    "groupKey",
    "groupCount",
    "replacementCount",
    "closeReason",
    "icon",
}
STRING_LIMITS = {
    "id": 96,
    "appKey": 192,
    "appName": 192,
    "summary": 512,
    "body": 4096,
    "groupKey": 192,
    "closeReason": 32,
    "icon": 512,
}


def state_dir() -> Path:
    override = os.environ.get("MAHO_NOTIFY_STATE_DIR")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return base / "maho" / "notify"


def state_path() -> Path:
    return state_dir() / "state.json"


def runtime_dir() -> Path:
    override = os.environ.get("MAHO_NOTIFY_RUNTIME_DIR")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    return base / "maho"


def status_path() -> Path:
    return runtime_dir() / "notify-status.json"


def default_state() -> dict[str, Any]:
    return {"version": VERSION, "dnd": False, "entries": []}


def _bounded_string(value: Any, limit: int) -> str:
    if value is None:
        return ""
    return str(value)[:limit]


def normalize_entry(raw: Any, now_ms: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    try:
        timestamp = int(raw.get("timestamp", 0))
    except (TypeError, ValueError):
        return None

    cutoff = now_ms - MAX_AGE_SECONDS * 1000
    if timestamp <= 0 or timestamp < cutoff:
        return None

    entry: dict[str, Any] = {}
    for field in ALLOWED_FIELDS:
        if field not in raw:
            continue
        value = raw[field]
        if field in STRING_LIMITS:
            entry[field] = _bounded_string(value, STRING_LIMITS[field])
        elif field in {"protocolId", "urgency", "timestamp", "groupCount", "replacementCount"}:
            try:
                entry[field] = int(value)
            except (TypeError, ValueError):
                entry[field] = 0
        elif field == "read":
            entry[field] = bool(value)

    if not entry.get("id"):
        return None

    entry["timestamp"] = timestamp
    entry["urgency"] = min(2, max(0, int(entry.get("urgency", 1))))
    entry["groupCount"] = max(1, int(entry.get("groupCount", 1)))
    entry["replacementCount"] = max(0, int(entry.get("replacementCount", 0)))
    entry["read"] = bool(entry.get("read", False))
    return entry


def normalize_state(raw: Any, now_ms: int | None = None) -> dict[str, Any]:
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if not isinstance(raw, dict):
        raw = {}

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in raw.get("entries", []):
        entry = normalize_entry(candidate, now_ms)
        if entry is None or entry["id"] in seen:
            continue
        seen.add(entry["id"])
        entries.append(entry)

    entries.sort(key=lambda item: int(item["timestamp"]), reverse=True)
    entries = entries[:MAX_ENTRIES]
    return {"version": VERSION, "dnd": bool(raw.get("dnd", False)), "entries": entries}


def _ensure_private_directory(directory: Path) -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)


def _atomic_json(path: Path, payload: dict[str, Any], prefix: str) -> None:
    directory = path.parent
    _ensure_private_directory(directory)
    fd, temporary_name = tempfile.mkstemp(prefix=prefix, suffix=".json", dir=directory)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_state() -> dict[str, Any]:
    path = state_path()
    _ensure_private_directory(path.parent)
    if not path.exists():
        return default_state()

    try:
        os.chmod(path, 0o600)
        with path.open("r", encoding="utf-8") as handle:
            return normalize_state(json.load(handle))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        corrupt = path.with_suffix(".json.corrupt")
        try:
            if corrupt.exists():
                corrupt.unlink()
            os.replace(path, corrupt)
            os.chmod(corrupt, 0o600)
        except OSError:
            pass
        return default_state()


def save_state(raw: Any) -> dict[str, Any]:
    state = normalize_state(raw)
    path = state_path()
    _atomic_json(path, state, ".state.")

    return state


def normalize_status(raw: Any, *, active: bool | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    try:
        unread_count = int(raw.get("unread_count", 0))
    except (TypeError, ValueError):
        unread_count = 0
    return {
        "version": STATUS_VERSION,
        "unread_count": min(MAX_ENTRIES, max(0, unread_count)),
        "dnd": bool(raw.get("dnd", False)),
        "active": bool(raw.get("active", False) if active is None else active),
    }


def publish_status(raw: Any, *, active: bool | None = None) -> dict[str, Any]:
    status = normalize_status(raw, active=active)
    _atomic_json(status_path(), status, ".notify-status.")
    return status


def metadata(state: dict[str, Any]) -> dict[str, Any]:
    entries = state.get("entries", [])
    return {
        "dnd": bool(state.get("dnd", False)),
        "history_count": len(entries),
        "unread_count": sum(1 for entry in entries if not entry.get("read", False)),
        "path": str(state_path()),
        "max_entries": MAX_ENTRIES,
        "max_age_days": MAX_AGE_SECONDS // 86400,
    }


def respond(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def serve() -> int:
    last_status = normalize_status({}, active=False)
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                operation = request.get("op")
                if operation == "load":
                    respond({"ok": True, "op": "state", "state": load_state()})
                elif operation == "save":
                    saved = save_state(request.get("state", {}))
                    respond({"ok": True, "op": "saved", "meta": metadata(saved)})
                elif operation == "publish_status":
                    last_status = publish_status(request.get("status", {}), active=True)
                    respond({"ok": True, "op": "status_published"})
                elif operation == "set_dnd":
                    state = load_state()
                    state["dnd"] = bool(request.get("enabled", False))
                    saved = save_state(state)
                    respond({"ok": True, "op": "dnd", "enabled": saved["dnd"]})
                elif operation == "clear":
                    state = load_state()
                    state["entries"] = []
                    saved = save_state(state)
                    respond({"ok": True, "op": "cleared", "meta": metadata(saved)})
                else:
                    respond({"ok": False, "error": "unsupported operation"})
            except Exception:
                respond({"ok": False, "error": "state operation failed"})
    finally:
        try:
            publish_status(last_status, active=False)
        except OSError:
            pass
    return 0


def self_test() -> int:
    original_override = os.environ.get("MAHO_NOTIFY_STATE_DIR")
    original_runtime_override = os.environ.get("MAHO_NOTIFY_RUNTIME_DIR")
    with tempfile.TemporaryDirectory(prefix="maho-notify-state-test-") as temporary:
        os.environ["MAHO_NOTIFY_STATE_DIR"] = temporary
        now_ms = int(time.time() * 1000)
        entries = [
            {
                "id": f"synthetic-{index}",
                "protocolId": index,
                "appKey": "synthetic.app",
                "appName": "Synthetic App",
                "summary": f"Synthetic {index}",
                "body": "Synthetic bounded body",
                "urgency": 1,
                "timestamp": now_ms - index,
                "read": False,
                "groupKey": "synthetic.app",
                "groupCount": 1,
                "replacementCount": 0,
                "closeReason": "expired",
                "icon": "",
            }
            for index in range(MAX_ENTRIES + 5)
        ]
        entries.append(
            {
                "id": "synthetic-old",
                "timestamp": now_ms - (MAX_AGE_SECONDS + 60) * 1000,
                "urgency": 1,
                "read": False,
            }
        )
        saved = save_state({"version": VERSION, "dnd": True, "entries": entries})
        assert len(saved["entries"]) == MAX_ENTRIES
        assert all(entry["id"] != "synthetic-old" for entry in saved["entries"])
        assert (state_dir().stat().st_mode & 0o777) == 0o700
        assert (state_path().stat().st_mode & 0o777) == 0o600

        os.environ["MAHO_NOTIFY_RUNTIME_DIR"] = str(Path(temporary) / "runtime")
        safe_status = publish_status({
            "unread_count": MAX_ENTRIES + 10,
            "dnd": True,
            "active": True,
            "summary": "must not persist",
            "body": "must not persist",
            "appName": "must not persist",
        })
        assert safe_status == {
            "version": STATUS_VERSION,
            "unread_count": MAX_ENTRIES,
            "dnd": True,
            "active": True,
        }
        persisted_status = json.loads(status_path().read_text(encoding="utf-8"))
        assert set(persisted_status) == {"version", "unread_count", "dnd", "active"}
        assert (runtime_dir().stat().st_mode & 0o777) == 0o700
        assert (status_path().stat().st_mode & 0o777) == 0o600

        state_path().write_text("{malformed", encoding="utf-8")
        os.chmod(state_path(), 0o600)
        recovered = load_state()
        assert recovered == default_state()
        corrupt = state_path().with_suffix(".json.corrupt")
        assert corrupt.is_file()
        assert (corrupt.stat().st_mode & 0o777) == 0o600

    if original_override is None:
        os.environ.pop("MAHO_NOTIFY_STATE_DIR", None)
    else:
        os.environ["MAHO_NOTIFY_STATE_DIR"] = original_override
    if original_runtime_override is None:
        os.environ.pop("MAHO_NOTIFY_RUNTIME_DIR", None)
    else:
        os.environ["MAHO_NOTIFY_RUNTIME_DIR"] = original_runtime_override
    print("PASS state self-test")
    return 0


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "status"
    if command == "serve":
        return serve()
    if command == "self-test":
        return self_test()
    if command == "status":
        respond(metadata(load_state()))
        return 0
    if command == "get-dnd":
        print("on" if load_state()["dnd"] else "off")
        return 0
    if command == "set-dnd" and len(argv) == 3 and argv[2] in {"on", "off"}:
        state = load_state()
        state["dnd"] = argv[2] == "on"
        save_state(state)
        print(argv[2])
        return 0
    if command == "toggle-dnd":
        state = load_state()
        state["dnd"] = not state["dnd"]
        saved = save_state(state)
        print("on" if saved["dnd"] else "off")
        return 0
    if command == "clear":
        state = load_state()
        state["entries"] = []
        save_state(state)
        return 0
    print("usage: state.py [serve|status|self-test|get-dnd|set-dnd on|set-dnd off|toggle-dnd|clear]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    os.umask(0o077)
    raise SystemExit(main(sys.argv))
