#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))

from maho_boot_authority import Digest  # noqa: E402
from maho_release_manifest import (  # noqa: E402
    Ed25519ReleaseSigner, ReleaseManifest, ReleaseManifestError, verify_release_manifest,
    verify_release_payloads,
)
from test_signed_boot_authority import fixture  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition: raise AssertionError(name)
    print("PASS", name)


def rejected(name: str, fn, contains: str) -> None:
    try: fn()
    except ReleaseManifestError as exc:
        check(name, contains in str(exc)); return
    raise AssertionError(name)


def main() -> None:
    generation, _, _, _ = fixture()
    signer = Ed25519ReleaseSigner.generate()
    manifest = ReleaseManifest(
        42, 3, "1.0.0", "a" * 40, "pkg-" + "b" * 64, "maho-runtime-1",
        generation, (generation.recovery_loader.artifact.identity,),
        (Digest.calculate(b"payload", algorithm="sha256", purpose="release-payload"),),
        1, 1, signer.authority_identity,
    )
    raw = manifest.canonical_bytes()
    sig = signer.sign(raw).canonical_bytes()
    verified = verify_release_manifest(raw, sig, signer.public_key_bytes(),
                                       expected_release_authority=signer.authority_identity,
                                       minimum_release_sequence=42, current_security_epoch=3)
    check("exact signed release bytes verify before parsing", verified.boot_generation.boot_generation_id == generation.boot_generation_id)
    verify_release_payloads(verified, {"release-payload": b"payload"})
    check("signed manifest binds exact payload bytes", True)
    rejected("mismatched release payload is rejected", lambda: verify_release_payloads(verified, {"release-payload": b"tampered"}), "payload_digest_mismatch")
    rejected("one-byte manifest tamper fails signature", lambda: verify_release_manifest(raw.replace(b"1.0.0", b"1.0.1"), sig, signer.public_key_bytes(), expected_release_authority=signer.authority_identity, minimum_release_sequence=42, current_security_epoch=3), "signature_invalid")
    duplicate = b'{"schema_version":1,"schema_version":1}'
    duplicate_sig = signer.sign(duplicate).canonical_bytes()
    rejected("signed duplicate keys are rejected", lambda: verify_release_manifest(duplicate, duplicate_sig, signer.public_key_bytes(), expected_release_authority=signer.authority_identity, minimum_release_sequence=1, current_security_epoch=1), "duplicate_key")
    rejected("stale signed release is rejected", lambda: verify_release_manifest(raw, sig, signer.public_key_bytes(), expected_release_authority=signer.authority_identity, minimum_release_sequence=43, current_security_epoch=3), "sequence_rollback")
    rejected("previous security epoch stays rejected", lambda: verify_release_manifest(raw, sig, signer.public_key_bytes(), expected_release_authority=signer.authority_identity, minimum_release_sequence=1, current_security_epoch=4), "security_epoch_mismatch")
    print("ALL MAHO RELEASE MANIFEST CONTRACTS PASS")


if __name__ == "__main__": main()
