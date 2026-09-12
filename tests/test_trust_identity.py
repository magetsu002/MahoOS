#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_trust_identity import (  # noqa: E402
    Artifact, ArtifactID, GenerationID, KernelGenerationID, ProvenanceID,
    TransactionID, TrustEvidence, TrustState, canonical_json, parse_trust_state,
    transition_trust,
)


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def rejects(name: str, operation) -> None:
    try:
        operation()
    except (TypeError, ValueError):
        print("PASS", name)
        return
    raise AssertionError(name)


check("canonical identity ignores object key ordering", TransactionID.derive({"b": 2, "a": 1}) == TransactionID.derive({"a": 1, "b": 2}))
check("canonical JSON is deterministic", canonical_json({"z": [2, 1], "a": "value"}) == '{"a":"value","z":[2,1]}')
check("generation identities are domain separated", str(GenerationID.derive({"root": "x"})).removeprefix("gen-") != str(KernelGenerationID.derive({"root": "x"})).removeprefix("kgen-"))

for cls, malformed in (
    (ArtifactID, "art-nope"), (TransactionID, "upd-legacy"),
    (GenerationID, "gen-abc"), (KernelGenerationID, "kgen-"),
    (ProvenanceID, "prv-" + "A" * 64),
):
    rejects(f"malformed {cls.__name__} is rejected", lambda cls=cls, malformed=malformed: cls(malformed))

provenance = ProvenanceID.derive({"builder": "maho-test", "revision": "a" * 40})
transaction = TransactionID.derive({"operation": "install", "candidate": "demo-2"})
first = Artifact.from_content(
    b"first", artifact_type="package", source_identity="core/demo",
    source_revision="a" * 40, producer_identity="arch-build-system",
    transaction_id=transaction, provenance_id=provenance,
    signing_authority="arch-keyring:test",
)
second = Artifact.from_content(
    b"second", artifact_type="package", source_identity="core/demo",
    source_revision="a" * 40, producer_identity="arch-build-system",
    transaction_id=transaction, provenance_id=provenance,
    signing_authority="arch-keyring:test",
)
check("artifact digest changes when content changes", first.artifact_id != second.artifact_id and first.content_sha256 != second.content_sha256)
check("signature evidence does not grant trust", first.signing_authority is not None and first.trust_state is TrustState.UNKNOWN)
check("artifact serialization roundtrips canonically", Artifact.parse(json.loads(first.canonical())).canonical() == first.canonical())

for state in TrustState:
    check(f"trust state {state.value} validates", parse_trust_state(state.value) is state)
rejects("unknown trust state is rejected", lambda: parse_trust_state("TRUST_ME"))

unknown_field = first.as_dict() | {"future_claim": True}
rejects("unknown future artifact fields fail closed", lambda: Artifact.parse(unknown_field))
forward = first.as_dict() | {"schema_version": 2}
rejects("forward artifact schema fails closed", lambda: Artifact.parse(forward))
rejects("UNKNOWN cannot become VERIFIED implicitly", lambda: transition_trust(TrustState.UNKNOWN, TrustState.VERIFIED))
verified = transition_trust(
    TrustState.UNKNOWN, TrustState.VERIFIED,
    TrustEvidence("independent-rebuild", "evidence:1", independently_verified=True),
)
check("independent evidence can explicitly verify UNKNOWN", verified is TrustState.VERIFIED)
rejects(
    "revocation cannot silently become VERIFIED",
    lambda: transition_trust(TrustState.REVOKED, TrustState.VERIFIED, TrustEvidence("review", "e:2", True)),
)
check(
    "revoked evidence requires explicit revalidation state",
    transition_trust(TrustState.REVOKED, TrustState.REVALIDATED, TrustEvidence("rebuild", "e:3", True)) is TrustState.REVALIDATED,
)
rejects("floats are excluded from canonical identities", lambda: canonical_json({"ambiguous": 0.1}))

print("ALL TRUST IDENTITY FOUNDATION TESTS PASS")
