#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


def child(token: str, root: Path) -> int:
    marker = f"MAHO_GUARDIAN_BAKEOFF_{token}"
    alpha = root / "alpha.txt"
    beta = root / "beta.txt"
    link = root / "beta.link"

    with alpha.open("wb") as handle:
        handle.write((marker + "\n").encode())
        handle.flush()
        os.fsync(handle.fileno())

    os.chmod(alpha, 0o640)
    alpha.rename(beta)
    link.symlink_to(beta.name)

    subprocess.run(
        ["/bin/sh", "-c", f"printf '%s\\n' '{marker}_GRANDCHILD' >> '{beta}'"],
        check=True,
    )
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("127.0.0.1", port))
    accepted, _ = server.accept()
    client.sendall(marker.encode())
    accepted.recv(4096)

    accepted.close()
    client.close()
    server.close()

    link.unlink()
    beta.unlink()

    print(json.dumps({
        "child_pid": os.getpid(),
        "loopback_port": port,
        "marker": marker,
    }, sort_keys=True))
    return 0


def run() -> int:
    token = secrets.token_hex(8)
    root = Path(tempfile.mkdtemp(prefix=f"maho-guardian-bakeoff-{token}-"))
    command = [sys.executable, str(Path(__file__).resolve()), "--child", token, str(root)]

    proc = subprocess.Popen(command, stdout=subprocess.PIPE, text=True)
    child_pid = proc.pid
    stdout, _ = proc.communicate(timeout=15)
    if proc.returncode != 0:
        raise SystemExit(f"workload child failed: {proc.returncode}")
    child_result = json.loads(stdout.strip())
    root.rmdir()

    manifest = {
        "schema_version": 1,
        "token": token,
        "marker": child_result["marker"],
        "root": str(root),
        "parent_pid": os.getpid(),
        "child_pid": child_pid,
        "loopback_port": child_result["loopback_port"],
        "expected": {
            "process_exec": [sys.executable, "/bin/sh"],
            "process_exit": True,
            "file_paths": [
                str(root / "alpha.txt"),
                str(root / "beta.txt"),
                str(root / "beta.link"),
            ],
            "file_operations": ["create", "write", "chmod", "rename", "symlink", "unlink"],
            "network_operations": ["bind", "listen", "connect", "accept", "close"],
            "network_scope": "loopback-only",
        },
    }
    print(json.dumps(manifest, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", nargs=2, metavar=("TOKEN", "ROOT"))
    args = parser.parse_args()

    if args.child:
        token, root = args.child
        return child(token, Path(root))
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
