#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import socket
import stat
import struct
import sys
from pathlib import Path

# Runtime security observers may execute from a content-addressed immutable
# release. Never let a privileged/root invocation create import bytecode inside
# that release, even when filesystem permission bits would not stop root.
sys.dont_write_bytecode = True

from security_probe import read_process, stable_hash

VERSION = 1

PRIVILEGED_EXACT = (
    ("etc/sudoers", "sudo-policy", "critical"),
    ("etc/ld.so.preload", "loader-preload", "critical"),
    ("etc/mkinitcpio.conf", "initramfs-policy", "high"),
    ("boot/loader/loader.conf", "boot-policy", "critical"),
)

PRIVILEGED_GLOBS = (
    ("etc/sudoers.d/*", "sudo-policy", "critical"),
    ("etc/polkit-1/rules.d/*.rules", "polkit-policy", "critical"),
    ("etc/modules-load.d/*", "kernel-module-policy", "high"),
    ("etc/modprobe.d/*", "kernel-module-policy", "high"),
    ("etc/pacman.d/hooks/*", "package-hook", "high"),
    ("etc/mkinitcpio.d/*", "initramfs-policy", "high"),
    ("boot/loader/entries/*.conf", "boot-entry", "critical"),
    ("etc/profile.d/*.sh", "system-shell-startup", "medium"),
    ("etc/cron.d/*", "system-cron", "high"),
)


def file_record(path: Path, fs_root: Path, kind: str, risk: str) -> dict | None:
    try:
        st = path.lstat()
    except (FileNotFoundError, PermissionError, OSError):
        return None
    try:
        rel = "/" + str(path.relative_to(fs_root)) if fs_root != Path("/") else str(path)
    except ValueError:
        rel = str(path)
    row = {
        "path": rel,
        "kind": kind,
        "risk": risk,
        "mode": stat.S_IMODE(st.st_mode),
        "uid": st.st_uid,
        "gid": st.st_gid,
        "type": "symlink" if stat.S_ISLNK(st.st_mode) else "file" if stat.S_ISREG(st.st_mode) else "other",
    }
    if stat.S_ISLNK(st.st_mode):
        try:
            row["target"] = os.readlink(path)
        except OSError:
            row["target"] = None
    elif stat.S_ISREG(st.st_mode):
        try:
            h = hashlib.sha256()
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            row["sha256"] = h.hexdigest()
        except (PermissionError, OSError):
            row["sha256"] = None
    return row


def privilege_inventory(args) -> dict:
    fs_root = Path(args.fs_root)
    home = Path(args.home)
    items = []
    for rel, kind, risk in PRIVILEGED_EXACT:
        row = file_record(fs_root / rel, fs_root, kind, risk)
        if row:
            items.append(row)
    for pattern, kind, risk in PRIVILEGED_GLOBS:
        for path in sorted(fs_root.glob(pattern)):
            row = file_record(path, fs_root, kind, risk)
            if row:
                items.append(row)
    authorized = file_record(home / ".ssh" / "authorized_keys", Path("/"), "ssh-authorized-keys", "high")
    if authorized:
        items.append(authorized)
    items.sort(key=lambda x: (x["kind"], x["path"]))
    core = {"version": VERSION, "kind": "privilege-boundary-inventory", "items": items}
    return {
        **core,
        "result": "observed",
        "state_sha256": stable_hash(core),
        "trust_note": "This is a transition reference for high-authority files, not a trusted-clean baseline.",
    }


def decode_ipv4(value: str) -> str:
    return socket.inet_ntoa(struct.pack("<I", int(value, 16)))


def decode_ipv6(value: str) -> str:
    raw = bytes.fromhex(value)
    raw = b"".join(raw[i : i + 4][::-1] for i in range(0, 16, 4))
    return socket.inet_ntop(socket.AF_INET6, raw)


def parse_tcp(path: Path, ipv6: bool) -> dict[str, dict]:
    rows = {}
    try:
        lines = path.read_text(errors="replace").splitlines()[1:]
    except OSError:
        return rows
    for line in lines:
        parts = line.split()
        if len(parts) < 10 or parts[3] != "0A":
            continue
        try:
            host_hex, port_hex = parts[1].split(":", 1)
            host = decode_ipv6(host_hex) if ipv6 else decode_ipv4(host_hex)
            port = int(port_hex, 16)
            inode = parts[9]
            ip = ipaddress.ip_address(host)
        except Exception:
            continue
        if ip.is_loopback:
            exposure = "loopback"
        elif ip.is_unspecified:
            exposure = "all-interfaces"
        else:
            exposure = "non-loopback-interface"
        rows[inode] = {
            "address": host,
            "port": port,
            "family": "ipv6" if ipv6 else "ipv4",
            "exposure": exposure,
        }
    return rows


def network_listeners(args) -> dict:
    proc_root = Path(args.proc_root)
    fs_root = Path(args.fs_root)
    uid = args.uid
    sockets = {}
    sockets.update(parse_tcp(proc_root / "net" / "tcp", False))
    sockets.update(parse_tcp(proc_root / "net" / "tcp6", True))
    listeners = []
    if proc_root.is_dir() and sockets:
        for proc in proc_root.iterdir():
            if not proc.name.isdigit() or not proc.is_dir():
                continue
            item = read_process(proc, fs_root)
            if not item or item.get("uid") != uid:
                continue
            fd_dir = proc / "fd"
            if not fd_dir.is_dir():
                continue
            seen = set()
            for fd in fd_dir.iterdir():
                try:
                    target = os.readlink(fd)
                except OSError:
                    continue
                if not target.startswith("socket:[") or not target.endswith("]"):
                    continue
                inode = target[8:-1]
                listener = sockets.get(inode)
                if not listener:
                    continue
                key = (inode, listener["address"], listener["port"])
                if key in seen:
                    continue
                seen.add(key)
                listeners.append(
                    {
                        **listener,
                        "pid": item["pid"],
                        "name": item.get("name"),
                        "exe": item.get("exe"),
                        "relative_exe": item.get("relative_exe"),
                    }
                )
    listeners.sort(key=lambda x: (x["exposure"], x["port"], x["pid"]))
    exposed = [x for x in listeners if x["exposure"] != "loopback"]
    core = {"version": VERSION, "kind": "network-listener-observations", "listeners": listeners, "exposed": exposed}
    return {
        **core,
        "result": "observed" if exposed else "clean",
        "state_sha256": stable_hash(core),
        "trust_note": "A non-loopback listener is exposure evidence, not proof of malicious behavior.",
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="security_boundary.py")
    sub = p.add_subparsers(dest="command", required=True)
    priv = sub.add_parser("privilege")
    priv.add_argument("--fs-root", default="/")
    priv.add_argument("--home", required=True)
    net = sub.add_parser("network")
    net.add_argument("--proc-root", default="/proc")
    net.add_argument("--fs-root", default="/")
    net.add_argument("--uid", type=int, required=True)
    sub.add_parser("doctor")
    return p


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "privilege":
        result = privilege_inventory(args)
    elif args.command == "network":
        result = network_listeners(args)
    elif args.command == "doctor":
        result = {
            "version": VERSION,
            "kind": "security-boundary-observer",
            "status": "ok",
            "automatic_system_mutation": False,
            "observes": ["privileged-file-transitions", "current-user-tcp-listeners"],
        }
    else:
        raise SystemExit("unknown command")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
