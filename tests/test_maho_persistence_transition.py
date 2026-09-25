#!/usr/bin/env python3
from __future__ import annotations

import copy
import gzip
import hashlib
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_persistence_transition import build_transition_plan, stable_hash  # noqa: E402
from security_probe import (  # noqa: E402
    transition_authority_payload,
    validate_legacy_transition_authority,
    validate_persistence_authority,
)


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print("PASS", label)


def rejected(call, contains: str) -> bool:
    try:
        call()
    except ValueError as exc:
        return contains in str(exc)
    return False


with tempfile.TemporaryDirectory() as raw:
    root = Path(raw)
    fs = root / "fs"
    db = root / "db"
    changed_path = fs / "etc/xdg/autostart/package.desktop"
    unrelated_path = fs / "etc/xdg/autostart/unrelated.desktop"
    changed_path.parent.mkdir(parents=True)
    changed_path.write_text("new package content\n")
    unrelated_path.write_text("unrelated content\n")
    before_sha = hashlib.sha256(b"old package content\n").hexdigest()
    after_sha = hashlib.sha256(changed_path.read_bytes()).hexdigest()
    unrelated_sha = hashlib.sha256(unrelated_path.read_bytes()).hexdigest()

    package = db / "demo-2.0-1"
    package.mkdir(parents=True)
    (package / "desc").write_text("%NAME%\ndemo\n\n%VERSION%\n2.0-1\n\n")
    (package / "files").write_text("%FILES%\netc/xdg/autostart/package.desktop\n\n")
    with gzip.open(package / "mtree", "wt") as stream:
        stream.write(
            "#mtree\n"
            f"./etc/xdg/autostart/package.desktop type=file sha256digest={after_sha}\n"
        )

    before_item = {
        "path": str(changed_path), "kind": "xdg-autostart-system",
        "type": "file", "sha256": before_sha,
    }
    after_item = {**before_item, "sha256": after_sha}
    baseline_inventory = {
        "version": 1, "kind": "persistence-inventory", "items": [before_item],
    }
    baseline = {
        "version": 1, "kind": "persistence-snapshot",
        "inventory": baseline_inventory,
        "state_sha256": stable_hash(baseline_inventory),
    }
    change = {"path": str(changed_path), "before": before_item, "after": after_item}
    persistence_check = {
        "attention_result": "changed",
        "baseline_state_sha256": baseline["state_sha256"],
        "unexpected_added": [], "unexpected_removed": [],
        "unexpected_changed": [change],
        "expected_changes": [{"path": str(root / "expected-maho.service")}],
    }
    transaction = {
        "transaction_id": "upd-20260925T100000Z-123456abcdef",
        "source_revision": "a" * 40,
        "state": "HEALTHY", "blockers": [],
        "activation": {"native_execution_certified": True},
        "recovery": {"native_l3_certified": True},
        "package_generation": {
            "id": "pkg-" + "b" * 64,
            "packages": [{
                "name": "demo", "installed_version": "1.0-1",
                "candidate_version": "2.0-1",
            }],
        },
    }
    publication = {
        "transaction_id": transaction["transaction_id"],
        "source_revision": transaction["source_revision"],
        "package_generation_id": transaction["package_generation"]["id"],
        "publication_id": "art-" + "c" * 64,
        "system_generation_id": "gen-" + "d" * 64,
        "kernel_generation_id": "kgen-" + "e" * 64,
        "fsroot": "/@", "previous_root_read_only": True,
    }

    def plan(*, base=baseline, observed=persistence_check, tx=transaction, live=publication):
        return build_transition_plan(
            baseline=base, check=observed, transaction=tx, publication=live,
            db_root=db, fs_root=fs, transaction_sha256="1" * 64,
            publication_sha256="2" * 64,
        )

    accepted = plan()
    check("exact package-owned HEALTHY transition is admitted", len(accepted["changes"]) == 1)
    check("transition binds exact before and after digests", accepted["changes"][0]["before"]["sha256"] == before_sha and accepted["changes"][0]["after"]["sha256"] == after_sha)
    check("transition binds package versions and mtree", accepted["changes"][0]["before_version"] == "1.0-1" and accepted["changes"][0]["after_version"] == "2.0-1" and accepted["changes"][0]["package_mtree_sha256"] == after_sha)
    check("transition binds package and live generation identities", accepted["package_generation_id"] == publication["package_generation_id"] and accepted["system_generation_id"] == publication["system_generation_id"])
    check("narrow target advances only the authorized file", accepted["target_inventory"]["items"] == [after_item])

    public_plan = {key: value for key, value in accepted.items() if key != "target_inventory"}
    authority_id = "pbt-" + accepted["target_state_sha256"][:16] + "-123456abcdef"
    previous_authority_id = "pba-" + baseline["state_sha256"][:16] + "-abcdef123456"
    authority = transition_authority_payload(
        public_plan,
        authority_id=authority_id,
        previous_authority_id=previous_authority_id,
        accepted_state=accepted["target_state_sha256"],
        accepted_at="2026-09-25T12:00:00.000Z",
        accepted_by_uid=1000,
    )
    check(
        "plan kind cannot shadow transition authority kind",
        authority["kind"] == "persistence-baseline-transition-authority",
    )
    authority_baseline = {
        "state_sha256": accepted["target_state_sha256"],
        "baseline_authority_id": authority_id,
        "baseline_authority_sha256": stable_hash(authority),
    }
    validate_persistence_authority(authority_baseline, authority)
    check("fresh transition authority validates after serialization", True)

    legacy = copy.deepcopy(authority)
    legacy["kind"] = "persistence-package-transition-plan"
    legacy_baseline = {
        "state_sha256": accepted["target_state_sha256"],
        "baseline_authority_id": authority_id,
        "baseline_authority_sha256": stable_hash(legacy),
    }
    validate_legacy_transition_authority(legacy_baseline, legacy)
    check("exact PR100 malformed authority is recognized only for bounded repair", True)
    stale_hash_baseline = {**legacy_baseline, "baseline_authority_sha256": "0" * 64}
    check(
        "tampered legacy receipt is rejected before repair",
        rejected(
            lambda: validate_legacy_transition_authority(stale_hash_baseline, legacy),
            "receipt hash mismatch",
        ),
    )

    wrong_version = copy.deepcopy(transaction)
    wrong_version["package_generation"]["packages"][0]["candidate_version"] = "9.0-1"
    check("wrong candidate version is denied", rejected(lambda: plan(tx=wrong_version), "version does not match"))

    altered = copy.deepcopy(persistence_check)
    altered["unexpected_changed"][0]["after"] = {**after_item, "sha256": "f" * 64}
    check("altered after hash is denied", rejected(lambda: plan(observed=altered), "differs from package metadata"))

    unrelated_before = {"path": str(unrelated_path), "kind": "xdg-autostart-system", "type": "file", "sha256": "3" * 64}
    unrelated_after = {**unrelated_before, "sha256": unrelated_sha}
    unrelated = copy.deepcopy(persistence_check)
    unrelated["unexpected_changed"].append({"path": str(unrelated_path), "before": unrelated_before, "after": unrelated_after})
    check("unrelated persistence change is denied", rejected(lambda: plan(observed=unrelated), "no installed package owns"))

    nonhealthy = copy.deepcopy(transaction)
    nonhealthy["state"] = "ACTIVE_VERIFYING"
    check("non-HEALTHY transaction is denied", rejected(lambda: plan(tx=nonhealthy), "unblocked HEALTHY"))

    stale_generation = copy.deepcopy(publication)
    stale_generation["package_generation_id"] = "pkg-" + "9" * 64
    check("wrong or stale current generation is denied", rejected(lambda: plan(live=stale_generation), "does not match"))

    added = copy.deepcopy(persistence_check)
    added["unexpected_added"] = [after_item]
    check("added persistence entry is outside the narrow boundary", rejected(lambda: plan(observed=added), "added or removed"))

    converged = copy.deepcopy(persistence_check)
    converged["attention_result"] = "clean"
    converged["unexpected_changed"] = []
    check("re-running after convergence is non-applicable", rejected(lambda: plan(base={**baseline, "inventory": accepted["target_inventory"], "state_sha256": accepted["target_state_sha256"]}, observed={**converged, "baseline_state_sha256": accepted["target_state_sha256"]}), "no unexplained"))
