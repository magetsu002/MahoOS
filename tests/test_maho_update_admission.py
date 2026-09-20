#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_admission import AdmissionOutcome  # noqa: E402
from guardian_native_admission import CandidateRoots  # noqa: E402
from maho_update_admission import (  # noqa: E402
    ProductionAdmissionError,
    admission_review_confirmation,
    evaluate_normal_production_candidate,
    evaluate_production_candidate,
    guardian_transaction_id,
    issue_activation_authority,
    verify_activation_authority,
)
from maho_update_state import create_transaction  # noqa: E402

NOW = datetime(2026, 9, 14, 4, 0, tzinfo=timezone.utc)
TX = "upd-20260914T040000Z-123456abcdef"
OTHER_TX = "upd-20260914T040001Z-fedcba654321"
SOURCE = "a" * 40


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def write_file(root: Path, relative: str, content: bytes, mode: int = 0o644) -> None:
    path = root / relative.lstrip("/")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(mode)


def package_db(root: Path, packages: dict[str, list[str]]) -> None:
    database = root / "var/lib/pacman/local"
    database.mkdir(parents=True, exist_ok=True)
    for name, files in packages.items():
        package = database / f"{name}-2.0-1"
        package.mkdir()
        (package / "desc").write_text(f"%NAME%\n{name}\n\n%VERSION%\n2.0-1\n")
        if files:
            rows = "\n".join(path.lstrip("/") for path in files)
            (package / "files").write_text(f"%FILES%\n{rows}\n")
        else:
            (package / "files").write_bytes(b"")


def transaction(txid: str = TX, *, foo_version: str = "2") -> dict:
    return create_transaction(
        transaction_id=txid,
        source_revision=SOURCE,
        packages=[
            {"name": "foo", "installed_version": "1", "candidate_version": foo_version,
             "repository": "core", "download_size": 1, "installed_size": 1, "roles": []},
            {"name": "bar", "installed_version": "1", "candidate_version": "2",
             "repository": "extra", "download_size": 1, "installed_size": 1, "roles": []},
        ],
        activation_requirements=["restart"],
        recovery_generation_id="g3-1234567890abcdef12345678",
        now=NOW,
    )


def candidate_roots(
    base: Path, *, candidate_id: str = "22222222-2222-2222-2222-222222222222",
    boundary_effect: bool = False,
) -> CandidateRoots:
    before = base / "base"
    candidate = base / "candidate"
    before.mkdir()
    candidate.mkdir()
    for root, foo, boot in ((before, b"foo-v1", b"boot-v1"), (candidate, b"foo-v2", b"boot-v2")):
        write_file(root, "/usr/bin/foo", foo, 0o755)
        write_file(root, "/usr/bin/bar", b"bar-v1", 0o755)
        foo_paths = ["/usr/bin/foo"]
        if boundary_effect:
            write_file(root, "/boot/vmlinuz-demo", boot, 0o644)
            foo_paths.append("/boot/vmlinuz-demo")
        package_db(root, {"foo": foo_paths, "bar": ["/usr/bin/bar"], "meta": []})
        (root / "home").mkdir()
    return CandidateRoots.create(
        transaction_id=guardian_transaction_id(TX),
        candidate_id=candidate_id,
        base_root=before,
        candidate_root=candidate,
    )


def rejected(name: str, fn, contains: str | None = None) -> None:
    try:
        fn()
    except ProductionAdmissionError as exc:
        check(name, contains is None or contains in str(exc))
        return
    raise AssertionError(name)


def main() -> None:
    plan = SimpleNamespace(boot_artifacts=())
    with tempfile.TemporaryDirectory(prefix="maho-production-admission-") as td:
        roots = candidate_roots(Path(td))
        tx = transaction()
        result = evaluate_production_candidate(roots, tx, plan)
        check("multi-package update does not invent cross-package overwrite", all(effect.kind.value != "PACKAGE_FILE_OVERRIDE" for effect in result.inspection.graph.effects))
        check("bounded multi-package update reaches ALLOW", result.decision.outcome is AdmissionOutcome.ALLOW)
        normal_result = evaluate_normal_production_candidate(roots, tx)
        check("normal admission tolerates legitimate zero-file meta packages", normal_result.inspection.graph.inspection_complete)
        check("ordinary same-package normal update reaches ALLOW", normal_result.decision.outcome is AdmissionOutcome.ALLOW and normal_result.promotion_authority is not None)
        authority = issue_activation_authority(
            result, update_transaction_id=TX, transaction=tx, source_revision=SOURCE,
        )
        verified = verify_activation_authority(
            authority.as_dict(), roots=roots, update_transaction_id=TX,
            transaction=tx, plan=plan, source_revision=SOURCE,
        )
        check("exact Admission authority survives process-boundary serialization", verified.authority_id == authority.authority_id)
        boot_generation = SimpleNamespace(
            boot_generation_id="bootgen-" + "1" * 64,
            source_revision=SOURCE,
            package_generation_id=tx["package_generation"]["id"],
            candidate_root_identity=result.inspection.candidate_root_identity,
        )
        boot_authority = SimpleNamespace(
            boot_authority_id="bootauth-" + "2" * 64,
            permitted_boot_generation_id=boot_generation.boot_generation_id,
            source_revision=SOURCE,
            release_sequence=7,
            security_epoch=2,
            device_signing_certificate_fingerprint="AB" * 32,
        )
        signed_authority = issue_activation_authority(
            result, update_transaction_id=TX, transaction=tx, source_revision=SOURCE,
            boot_generation=boot_generation, boot_authority=boot_authority,
        )
        signed_verified = verify_activation_authority(
            signed_authority.as_dict(), roots=roots, update_transaction_id=TX,
            transaction=tx, plan=plan, source_revision=SOURCE,
            boot_generation=boot_generation, boot_authority=boot_authority,
        )
        check("activation authority binds BootGeneration, BootAuthority, sequence, epoch and signer",
              signed_verified.boot_generation_id == boot_generation.boot_generation_id
              and signed_verified.boot_authority_id == boot_authority.boot_authority_id
              and signed_verified.release_sequence == 7 and signed_verified.security_epoch == 2)
        rejected(
            "signed activation authority cannot be consumed without boot evidence",
            lambda: verify_activation_authority(
                signed_authority.as_dict(), roots=roots, update_transaction_id=TX,
                transaction=tx, plan=plan, source_revision=SOURCE,
            ),
            "signed_boot_context_missing",
        )
        check("review token binds exact mutation graph", admission_review_confirmation(TX, result.inspection.graph.graph_id).endswith(str(result.inspection.graph.graph_id)))

        with tempfile.TemporaryDirectory(prefix="maho-production-admission-review-") as review_td:
            review_roots = candidate_roots(Path(review_td), boundary_effect=True)
            review_plan = SimpleNamespace(boot_artifacts=("/boot/vmlinuz-demo",))
            reviewed = evaluate_production_candidate(review_roots, tx, review_plan)
            check("declared boot boundary requires explicit REVIEW", reviewed.decision.outcome is AdmissionOutcome.REVIEW and reviewed.promotion_authority is None)
            approved = evaluate_production_candidate(
                review_roots, tx, review_plan,
                known_safe_graph_ids=(reviewed.inspection.graph.graph_id,),
            )
            check("exact reviewed graph alone becomes ALLOW", approved.decision.outcome is AdmissionOutcome.ALLOW and approved.promotion_authority is not None)
            check("different graph cannot reuse review approval", approved.inspection.graph.graph_id == reviewed.inspection.graph.graph_id)

        rejected(
            "authority from another update transaction fails closed",
            lambda: verify_activation_authority(
                authority.as_dict(), roots=roots, update_transaction_id=OTHER_TX,
                transaction=tx, plan=plan, source_revision=SOURCE,
            ),
            "activation_authority_context_mismatch",
        )
        rejected(
            "stale source authority fails closed",
            lambda: verify_activation_authority(
                authority.as_dict(), roots=roots, update_transaction_id=TX,
                transaction=tx, plan=plan, source_revision="b" * 40,
            ),
            "activation_authority_context_mismatch",
        )
        changed_generation = transaction(foo_version="3")
        rejected(
            "wrong package generation fails closed",
            lambda: verify_activation_authority(
                authority.as_dict(), roots=roots, update_transaction_id=TX,
                transaction=changed_generation, plan=plan, source_revision=SOURCE,
            ),
            "activation_authority_context_mismatch",
        )
        wrong_candidate = CandidateRoots.create(
            transaction_id=roots.transaction_id,
            candidate_id="33333333-3333-3333-3333-333333333333",
            base_root=roots.base_root,
            candidate_root=roots.candidate_root,
        )
        rejected(
            "wrong candidate identity fails closed",
            lambda: verify_activation_authority(
                authority.as_dict(), roots=wrong_candidate, update_transaction_id=TX,
                transaction=tx, plan=plan, source_revision=SOURCE,
            ),
            "activation_authority_context_mismatch",
        )
        tampered = deepcopy(authority.as_dict())
        tampered["graph_id"] = "art-" + "0" * 64
        rejected(
            "changed mutation-graph authority fails digest validation",
            lambda: verify_activation_authority(
                tampered, roots=roots, update_transaction_id=TX,
                transaction=tx, plan=plan, source_revision=SOURCE,
            ),
            "activation_authority_digest_mismatch",
        )
        tampered_runtime = deepcopy(authority.as_dict())
        tampered_runtime["runtime_evidence_sha256"] = "0" * 64
        rejected(
            "changed runtime evidence authority fails digest validation",
            lambda: verify_activation_authority(
                tampered_runtime, roots=roots, update_transaction_id=TX,
                transaction=tx, plan=plan, source_revision=SOURCE,
            ),
            "activation_authority_digest_mismatch",
        )

        write_file(roots.candidate_root, "/usr/bin/foo", b"post-admission-drift", 0o755)
        rejected(
            "post-admission filesystem drift invalidates activation authority",
            lambda: verify_activation_authority(
                authority.as_dict(), roots=roots, update_transaction_id=TX,
                transaction=tx, plan=plan, source_revision=SOURCE,
            ),
            "promotion_authority_binding_mismatch",
        )

    with tempfile.TemporaryDirectory(prefix="maho-production-admission-boot-drift-") as td:
        boot_roots = candidate_roots(Path(td), boundary_effect=True)
        boot_plan = SimpleNamespace(boot_artifacts=("/boot/vmlinuz-demo",))
        reviewed = evaluate_production_candidate(boot_roots, transaction(), boot_plan)
        approved = evaluate_production_candidate(
            boot_roots, transaction(), boot_plan,
            known_safe_graph_ids=(reviewed.inspection.graph.graph_id,),
        )
        boot_authority = issue_activation_authority(
            approved, update_transaction_id=TX, transaction=transaction(), source_revision=SOURCE,
        )
        write_file(boot_roots.candidate_root, "/boot/vmlinuz-demo", b"boot-drift", 0o644)
        rejected(
            "post-admission boot artifact drift invalidates activation authority",
            lambda: verify_activation_authority(
                boot_authority.as_dict(), roots=boot_roots, update_transaction_id=TX,
                transaction=transaction(), plan=boot_plan, source_revision=SOURCE,
            ),
            "promotion_authority_binding_mismatch",
        )

    with tempfile.TemporaryDirectory(prefix="maho-production-admission-module-drift-") as td:
        module_roots = candidate_roots(Path(td))
        module_tx = transaction()
        module_plan = SimpleNamespace(boot_artifacts=())
        admitted = evaluate_production_candidate(module_roots, module_tx, module_plan)
        module_authority = issue_activation_authority(
            admitted, update_transaction_id=TX, transaction=module_tx, source_revision=SOURCE,
        )
        write_file(module_roots.candidate_root, "/usr/lib/modules/7.2/extra/drift.ko", b"module-drift", 0o644)
        rejected(
            "post-admission kernel-module drift invalidates activation authority",
            lambda: verify_activation_authority(
                module_authority.as_dict(), roots=module_roots, update_transaction_id=TX,
                transaction=module_tx, plan=module_plan, source_revision=SOURCE,
            ),
            "promotion_authority_binding_mismatch",
        )

    print("ALL MAHO PRODUCTION ADMISSION CONTRACTS PASS")


if __name__ == "__main__":
    main()
