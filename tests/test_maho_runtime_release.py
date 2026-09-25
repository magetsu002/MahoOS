#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_runtime_release import verify_release  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def payload_identity(stage: Path) -> str:
    lines: list[bytes] = []
    for path in sorted(
        (p for p in stage.rglob("*") if p.is_file() and p.name != "manifest.json"),
        key=lambda p: ("./" + p.relative_to(stage).as_posix()).encode(),
    ):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  ./{path.relative_to(stage).as_posix()}\n".encode())
    return hashlib.sha256(b"".join(lines)).hexdigest()


def make_release(releases: Path, revision: str, *, development: bool = False, legacy: bool = False) -> Path:
    stage = releases / f"stage-{revision[:8]}"
    (stage / "bin").mkdir(parents=True)
    (stage / "share/maho").mkdir(parents=True)
    (stage / "bin/probe").write_text("#!/usr/bin/env bash\nexit 0\n")
    (stage / "share/maho/runtime-source-revision").write_text(revision + "\n")
    if not legacy:
        (stage / "share/maho/runtime-deployment.json").write_text(json.dumps({
            "version": 1,
            "deployment_class": "development" if development else "production",
            "source_dirty": development,
            "trust_eligible": not development,
        }, sort_keys=True) + "\n")
    identity = payload_identity(stage)
    final = releases / identity
    stage.rename(final)
    manifest = {
        "version": 3,
        "content_sha256": identity,
        "source_revision": revision,
        "installed_at": "2026-09-09T00:00:00+00:00",
    }
    if not legacy:
        manifest.update({
            "deployment_class": "development" if development else "production",
            "source_dirty": development,
            "trust_eligible": not development,
        })
    (final / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    for path in sorted(final.rglob("*"), reverse=True):
        if path.is_file():
            os.chmod(path, 0o444)
        elif path.is_dir():
            os.chmod(path, 0o555)
    os.chmod(final, 0o555)
    return final


def make_writable(path: Path) -> None:
    os.chmod(path, path.stat().st_mode | 0o200)


def main() -> None:
    with tempfile.TemporaryDirectory() as raw:
        base = Path(raw)
        releases = base / "runtime/releases"
        releases.mkdir(parents=True)
        valid = make_release(releases, "a" * 40)

        result = verify_release(valid, releases)
        check("valid immutable release verifies", result.verified and not result.reasons)
        check("verified release exposes provenance", result.source_revision == "a" * 40 and result.content_sha256 == valid.name)
        check("production release is trust eligible", result.trust_eligible and result.deployment_class == "production")

        development = make_release(releases, "e" * 40, development=True)
        result = verify_release(development, releases)
        check("development release has verified bytes but no production trust", result.verified and not result.trust_eligible and result.deployment_class == "development")

        legacy = make_release(releases, "1" * 40, legacy=True)
        result = verify_release(legacy, releases)
        check("legacy release remains recoverable but cannot claim production trust", result.verified and not result.trust_eligible and result.deployment_class == "legacy-unclassified")

        nested_parent = releases / "nested"
        nested_parent.mkdir()
        nested = nested_parent / valid.name
        shutil.copytree(valid, nested)
        result = verify_release(nested, releases)
        check("release outside direct releases membership is rejected", not result.verified and "release_not_direct_child" in result.reasons)

        bad_manifest = make_release(releases, "b" * 40)
        make_writable(bad_manifest)
        make_writable(bad_manifest / "manifest.json")
        (bad_manifest / "manifest.json").write_text("{broken\n")
        os.chmod(bad_manifest / "manifest.json", 0o444)
        os.chmod(bad_manifest, 0o555)
        result = verify_release(bad_manifest, releases)
        check("malformed manifest is rejected", not result.verified and "manifest_invalid" in result.reasons)

        bad_provenance = make_release(releases, "c" * 40)
        make_writable(bad_provenance)
        provenance = bad_provenance / "share/maho/runtime-source-revision"
        make_writable(provenance)
        provenance.write_text("different\n")
        os.chmod(provenance, 0o444)
        os.chmod(bad_provenance, 0o555)
        result = verify_release(bad_provenance, releases)
        check("provenance mismatch is rejected", not result.verified and "source_provenance_mismatch" in result.reasons)
        check("payload drift is independently rejected", "payload_content_identity_mismatch" in result.reasons)

        writable = make_release(releases, "d" * 40)
        make_writable(writable / "bin/probe")
        result = verify_release(writable, releases)
        check("writable immutable payload is rejected", not result.verified and "immutable_payload_writable" in result.reasons)

        missing = verify_release(releases / ("f" * 64), releases)
        check("missing release fails closed", not missing.verified and "release_unavailable" in missing.reasons)

    print("ALL MAHO RUNTIME RELEASE VERIFICATION TESTS PASS")


if __name__ == "__main__":
    main()
