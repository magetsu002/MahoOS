#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_admission import AdmissionOutcome, CandidateDeclaration, EffectKind  # noqa: E402
from guardian_native_admission import (  # noqa: E402
    CandidateRoots, NativeAdmissionError, admit_candidate, candidate_first_admission,
    filesystem_observations, package_ownership, parse_runtime_evidence,
    parse_declaration, revalidate_promotion_authority, root_identity,
    verify_promotion_authority,
)
from maho_trust_identity import TransactionID  # noqa: E402


TX = TransactionID.derive({"native-admission": "test"})
CANDIDATE = "candidate-test-001"


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
        package = database / f"{name}-1.0-1"
        package.mkdir()
        (package / "desc").write_text(f"%NAME%\n{name}\n\n%VERSION%\n1.0-1\n")
        if files:
            rows = "\n".join(path.lstrip("/") for path in files)
            (package / "files").write_text(f"%FILES%\n{rows}\n")
        else:
            (package / "files").write_bytes(b"")


def roots(tmp: Path, *, before: dict[str, tuple[bytes, int]], after: dict[str, tuple[bytes, int]],
          before_packages=None, after_packages=None) -> CandidateRoots:
    tmp.mkdir(parents=True, exist_ok=True)
    base = tmp / "base"
    candidate = tmp / "candidate"
    base.mkdir()
    candidate.mkdir()
    for path, (content, mode) in before.items():
        write_file(base, path, content, mode)
    for path, (content, mode) in after.items():
        write_file(candidate, path, content, mode)
    package_db(base, {"demo": list(before)} if before_packages is None else before_packages)
    package_db(candidate, {"demo": list(after)} if after_packages is None else after_packages)
    (base / "home").mkdir()
    (candidate / "home").mkdir()
    return CandidateRoots.create(
        transaction_id=TX,
        candidate_id=CANDIDATE,
        base_root=base,
        candidate_root=candidate,
    )


def runtime(
    roots_value, *, before=(), after=(), complete=True, isolated=True,
    candidate=CANDIDATE, observer="guardian-native-runtime-observer-v1",
):
    value = {
        "schema_version": 1,
        "kind": "candidate-runtime-observation",
        "candidate_id": candidate,
        "transaction_id": str(roots_value.transaction_id),
        "base_root_identity": root_identity(roots_value.base_root),
        "candidate_root_identity": root_identity(roots_value.candidate_root),
        "observer_identity": observer,
        "independently_observed": True,
        "network_namespace_isolated": isolated,
        "production_root_read_only": isolated,
        "execution_complete": complete,
        "listeners_before": list(before),
        "listeners_after": list(after),
    }
    return parse_runtime_evidence(value, roots=roots_value), value


def declaration(paths, effects=(EffectKind.FILE,)):
    return CandidateDeclaration("demo", tuple(paths), tuple(effects))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="guardian-zero-file-package-") as td:
        root = Path(td)
        package_db(root, {"meta": [], "demo": ["/usr/bin/demo"]})
        write_file(root, "/usr/bin/demo", b"demo", 0o755)
        ownership, errors = package_ownership(root)
        check("zero-file Pacman package is complete empty ownership evidence", not errors and ownership.get("/usr/bin/demo") == "demo" and "meta" not in ownership.values())
        malformed = root / "var/lib/pacman/local/broken-1.0-1"
        malformed.mkdir()
        (malformed / "desc").write_text("%NAME%\nbroken\n\n%VERSION%\n1.0-1\n")
        (malformed / "files").write_text("not-a-pacman-file-manifest\n")
        _, malformed_errors = package_ownership(root)
        check("nonempty malformed Pacman file manifest still fails closed", any(item.startswith("package_file_manifest_missing:broken-") for item in malformed_errors))

    with tempfile.TemporaryDirectory(prefix="guardian-special-object-") as td:
        root = Path(td)
        package_db(root, {})
        socket_path = root / "etc/pacman.d/gnupg/S.gpg-agent"
        socket_path.parent.mkdir(parents=True)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.bind(str(socket_path))
            observations, errors = filesystem_observations(root, {})
            special = observations.get("/etc/pacman.d/gnupg/S.gpg-agent")
            check("persistent Unix socket is observed instead of poisoning inspection", not errors and special is not None and special.file_type == "other")
        finally:
            sock.close()

    try:
        parse_declaration({
            "schema_version": 1,
            "package_identity": "demo",
            "path_prefixes": ["/"],
            "effect_kinds": ["FILE"],
        })
    except NativeAdmissionError:
        check("unbounded root declaration is refused", True)
    else:
        raise AssertionError("unbounded declaration accepted")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        candidate = roots(
            tmp,
            before={"/usr/bin/demo": (b"v1", 0o755)},
            after={"/usr/bin/demo": (b"v2", 0o755)},
        )
        runtime_evidence, runtime_value = runtime(candidate)
        class Factory:
            def __init__(self):
                self.calls = []

            def create_isolated_candidate(self, transaction_id):
                self.calls.append(("create", transaction_id))
                return candidate

            def observe_isolated_runtime(self, roots_value):
                self.calls.append(("observe", roots_value.candidate_id))
                return runtime_evidence

        factory = Factory()
        ordered = candidate_first_admission(
            factory,
            transaction_id=TX,
            declaration=declaration(("/usr/bin/demo",)),
        )
        check("candidate-first boundary creates before isolated observation", factory.calls == [("create", TX), ("observe", CANDIDATE)])
        check("candidate-first boundary admits only after inspection", ordered.decision.outcome is AdmissionOutcome.ALLOW)
        allowed = admit_candidate(candidate, declaration(("/usr/bin/demo",)), runtime_evidence)
        check("isolated candidate is inspected before admission", allowed.inspection.graph.inspection_complete)
        check("bounded candidate reaches ALLOW", allowed.decision.outcome is AdmissionOutcome.ALLOW)
        check("ALLOW creates exact promotion authority", allowed.promotion_authority is not None)
        verified = verify_promotion_authority(
            allowed.promotion_authority.as_dict(), inspection=allowed.inspection,
        )
        check("promotion authority roundtrips with exact graph binding", verified.graph_id == allowed.inspection.graph.graph_id)

        write_file(candidate.candidate_root, "/usr/bin/demo", b"post-admission-drift", 0o755)
        try:
            revalidate_promotion_authority(
                allowed.promotion_authority.as_dict(),
                roots=candidate,
                declaration=declaration(("/usr/bin/demo",)),
                runtime=runtime_evidence,
            )
        except NativeAdmissionError as exc:
            check("candidate drift after ALLOW invalidates promotion authority", str(exc) == "promotion_authority_binding_mismatch")
        else:
            raise AssertionError("drifted candidate retained promotion authority")
        write_file(candidate.candidate_root, "/usr/bin/demo", b"v2", 0o755)

        tampered = allowed.promotion_authority.as_dict()
        tampered["candidate_id"] = "candidate-other"
        try:
            verify_promotion_authority(tampered, inspection=allowed.inspection)
        except NativeAdmissionError:
            check("promotion authority cannot move to another candidate", True)
        else:
            raise AssertionError("tampered authority accepted")

        changed_root = tmp / "changed"
        changed = roots(
            changed_root,
            before={"/usr/bin/demo": (b"v1", 0o755)},
            after={"/usr/bin/demo": (b"different-v2", 0o755)},
        )
        changed_result = admit_candidate(changed, declaration(("/usr/bin/demo",)), runtime(changed)[0])
        check("mutation graph binds exact file content", changed_result.inspection.graph.graph_id != allowed.inspection.graph.graph_id)

        cli_decl = tmp / "declaration.json"
        cli_runtime = tmp / "runtime.json"
        cli_decl.write_text(json.dumps({
            "schema_version": 1,
            "package_identity": "demo",
            "path_prefixes": ["/usr/bin/demo"],
            "effect_kinds": ["FILE"],
        }))
        cli_runtime.write_text(json.dumps(runtime_value))
        cp = subprocess.run([
            sys.executable, str(ROOT / "bin/maho-admit"),
            "--base-root", str(candidate.base_root),
            "--candidate-root", str(candidate.candidate_root),
            "--candidate-id", CANDIDATE,
            "--transaction-id", str(TX),
            "--declaration", str(cli_decl),
            "--runtime-evidence", str(cli_runtime),
        ], text=True, capture_output=True)
        cli_result = json.loads(cp.stdout)
        check("native CLI emits machine-readable ALLOW authority", cp.returncode == 0 and cli_result["promotion_authority"] is not None)

    with tempfile.TemporaryDirectory() as td:
        candidate = roots(
            Path(td),
            before={"/usr/bin/shared": (b"other", 0o755)},
            after={"/usr/bin/shared": (b"demo", 0o755)},
            before_packages={"other": ["/usr/bin/shared"]},
            after_packages={"demo": ["/usr/bin/shared"]},
        )
        result = admit_candidate(
            candidate,
            declaration(("/usr/bin/shared",), (EffectKind.FILE,)),
            runtime(candidate)[0],
        )
        check("cross-package overwrite is detected from real package databases", any(effect.kind is EffectKind.PACKAGE_FILE_OVERRIDE for effect in result.inspection.graph.effects))
        check("undeclared cross-package overwrite is REJECT with no authority", result.decision.outcome is AdmissionOutcome.REJECT and result.promotion_authority is None)

    adversarial = (
        ("service", "/usr/lib/systemd/system/demo.service", EffectKind.SYSTEM_SERVICE),
        ("persistence", "/etc/xdg/autostart/demo.desktop", EffectKind.STARTUP_PERSISTENCE),
        ("privileged file", "/etc/sudoers.d/demo", EffectKind.PRIVILEGE_AUTHORITY),
        ("boot effect", "/boot/EFI/Linux/demo.efi", EffectKind.BOOT_STATE),
        ("package hook", "/usr/share/libalpm/hooks/demo.hook", EffectKind.PACMAN_HOOK),
        ("kernel module", "/usr/lib/modules/6.18/extra/demo.ko", EffectKind.KERNEL_MODULE),
    )
    for label, path, kind in adversarial:
        with tempfile.TemporaryDirectory() as td:
            candidate = roots(Path(td), before={}, after={path: (b"payload", 0o644)})
            result = admit_candidate(candidate, declaration((path,), (EffectKind.FILE,)), runtime(candidate)[0])
            check(f"native inspector detects {label}", any(effect.kind is kind for effect in result.inspection.graph.effects))
            check(f"undeclared {label} is rejected", result.decision.outcome is AdmissionOutcome.REJECT and result.promotion_authority is None)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        candidate = roots(tmp, before={}, after={"/usr/bin/demo": (b"demo", 0o4755)})
        result = admit_candidate(candidate, declaration(("/usr/bin/demo",)), runtime(candidate)[0])
        check("new setuid privilege is a distinct effect", any(effect.kind is EffectKind.PRIVILEGE_AUTHORITY for effect in result.inspection.graph.effects))
        check("undeclared setuid authority is rejected", result.decision.outcome is AdmissionOutcome.REJECT)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        candidate = roots(tmp, before={}, after={}, before_packages={}, after_packages={})
        link = candidate.candidate_root / "etc/systemd/system/multi-user.target.wants/demo.service"
        link.parent.mkdir(parents=True)
        link.symlink_to("/usr/lib/systemd/system/demo.service")
        package_db(candidate.candidate_root, {"demo": ["/etc/systemd/system/multi-user.target.wants/demo.service"]})
        result = admit_candidate(
            candidate,
            declaration(("/etc/systemd/system",), (EffectKind.SYSTEM_SERVICE,)),
            runtime(candidate)[0],
        )
        check("systemd enablement symlink is persistence", any(effect.kind is EffectKind.STARTUP_PERSISTENCE for effect in result.inspection.graph.effects))
        check("undeclared enablement is rejected", result.decision.outcome is AdmissionOutcome.REJECT)

    with tempfile.TemporaryDirectory() as td:
        candidate = roots(
            Path(td),
            before={"/usr/bin/demo": (b"v1", 0o755)},
            after={"/usr/bin/demo": (b"v2", 0o755)},
        )
        listener = {"protocol": "tcp", "address": "0.0.0.0", "port": 8443}
        listener_runtime = runtime(candidate, after=(listener,))[0]
        result = admit_candidate(candidate, declaration(("/usr/bin/demo",)), listener_runtime)
        check("new runtime listener is in actual mutation graph", any(effect.kind is EffectKind.NETWORK_LISTENER for effect in result.inspection.graph.effects))
        check("undeclared listener is rejected", result.decision.outcome is AdmissionOutcome.REJECT)
        reviewed = admit_candidate(
            candidate,
            declaration(("/usr/bin/demo",), (EffectKind.FILE, EffectKind.NETWORK_LISTENER)),
            listener_runtime,
        )
        check("declared listener requires REVIEW and cannot promote", reviewed.decision.outcome is AdmissionOutcome.REVIEW and reviewed.promotion_authority is None)

        incomplete = admit_candidate(candidate, declaration(("/usr/bin/demo",)), runtime(candidate, complete=False)[0])
        check("incomplete runtime evidence fails closed", incomplete.decision.outcome is AdmissionOutcome.REJECT and not incomplete.inspection.graph.inspection_complete)
        check("runtime completeness is retained in native rejection evidence", incomplete.inspection.runtime_complete is False and incomplete.inspection.runtime_isolated is True)
        unisolated = admit_candidate(candidate, declaration(("/usr/bin/demo",)), runtime(candidate, isolated=False)[0])
        check("runtime probe outside isolation fails closed", unisolated.decision.outcome is AdmissionOutcome.REJECT)
        check("runtime isolation is retained in native rejection evidence", unisolated.inspection.runtime_complete is True and unisolated.inspection.runtime_isolated is False)

        try:
            runtime(candidate, observer="self-declared-observer")
        except NativeAdmissionError as exc:
            check("unregistered runtime observer is refused", str(exc) == "runtime_evidence_observer_invalid")
        else:
            raise AssertionError("unregistered runtime observer accepted")

        try:
            runtime(candidate, after=(listener, listener))
        except NativeAdmissionError as exc:
            check("ambiguous duplicate listener evidence is refused", str(exc) == "runtime_listener_identity_ambiguous")
        else:
            raise AssertionError("duplicate listener evidence accepted")

        write_file(candidate.candidate_root, "/home/user/private", b"personal")
        personal = admit_candidate(candidate, declaration(("/usr/bin/demo",)), runtime(candidate)[0])
        check("candidate cannot absorb personal-data scope", personal.decision.outcome is AdmissionOutcome.REJECT and "personal_data_scope_not_isolated:/home" in personal.inspection.errors)

    with tempfile.TemporaryDirectory() as td:
        candidate = roots(
            Path(td),
            before={"/usr/bin/demo": (b"same", 0o755)},
            after={"/usr/bin/demo": (b"same", 0o755)},
        )
        no_op = admit_candidate(candidate, declaration(("/usr/bin/demo",)), runtime(candidate)[0])
        check("empty candidate mutation graph is rejected", no_op.decision.reasons == ("candidate_has_no_observed_mutation",))

        shutil.rmtree(candidate.candidate_root / "var/lib/pacman/local")
        missing_package_db = admit_candidate(candidate, declaration(("/usr/bin/demo",)), runtime(candidate)[0])
        check("missing candidate package evidence fails closed", missing_package_db.decision.outcome is AdmissionOutcome.REJECT and not missing_package_db.inspection.graph.inspection_complete)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        root.mkdir(exist_ok=True)
        try:
            CandidateRoots.create(
                transaction_id=TX,
                candidate_id=CANDIDATE,
                base_root=root,
                candidate_root=root,
            )
        except NativeAdmissionError as exc:
            check("live/base root cannot be its own candidate", str(exc) == "candidate_is_not_isolated")
        else:
            raise AssertionError("non-isolated candidate accepted")

    print("ALL GUARDIAN NATIVE ADMISSION TESTS PASS")


if __name__ == "__main__":
    main()
