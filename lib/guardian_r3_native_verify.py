#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, pathlib, sys
HERE = pathlib.Path(__file__).resolve().parent
SOURCE_LIB = HERE if (HERE / "guardian_recovery_r3_executor.py").is_file() else HERE.parent / "lib"
sys.path.insert(0, str(SOURCE_LIB))
from guardian_recovery_r3_executor import parse_envelope
from maho_trust_identity import ArtifactID, canonical_bytes

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def package_set(root: pathlib.Path) -> str:
    local = root / "var/lib/pacman/local"
    names = sorted(p.name for p in local.iterdir() if p.is_dir())
    return sha(("\n".join(names) + "\n").encode())

def modules_id(root: pathlib.Path, release: str) -> str:
    base = root / "usr/lib/modules" / release
    rows = []
    for p in sorted(x for x in base.rglob("*") if x.is_file() and not x.is_symlink()):
        rows.append({"path": str(p.relative_to(base)), "sha256": sha(p.read_bytes())})
    payload = canonical_bytes({"release": release, "files": rows})
    return str(ArtifactID.from_content(payload))
def artifact_path(evidence: pathlib.Path, artifact_id: str) -> pathlib.Path:
    digest = artifact_id.removeprefix("art-")
    return evidence / "artifacts/sha256" / digest[:2] / digest[2:]

def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: guardian_r3_native_verify.py COMMAND ...")
    cmd = sys.argv[1]
    if cmd == "package-set" and len(sys.argv) == 3:
        print(package_set(pathlib.Path(sys.argv[2]))); return 0
    if cmd == "modules-id" and len(sys.argv) == 4:
        print(modules_id(pathlib.Path(sys.argv[2]), sys.argv[3])); return 0
    if cmd == "artifact-path" and len(sys.argv) == 4:
        p = artifact_path(pathlib.Path(sys.argv[2]), sys.argv[3])
        if not p.is_file(): raise SystemExit("artifact missing")
        print(p); return 0
    if cmd == "intent" and len(sys.argv) == 3:
        intent = parse_envelope(json.loads(pathlib.Path(sys.argv[2]).read_text()))
        print(json.dumps(intent.as_dict(), sort_keys=True)); return 0
    raise SystemExit("invalid arguments")

if __name__ == "__main__":
    raise SystemExit(main())
