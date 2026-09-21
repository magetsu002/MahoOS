#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_admission import (  # noqa: E402
    AdmissionOutcome, CandidateDeclaration, EffectKind, FileObservation,
    ListenerObservation, derive_mutation_graph, evaluate_admission,
)
from maho_trust_identity import TransactionID  # noqa: E402


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def observed(content: bytes, owner=None, mode=0o644):
    return FileObservation(hashlib.sha256(content).hexdigest(), mode, owner)


TX = TransactionID.derive({"candidate": "demo-2"})
safe_declaration = CandidateDeclaration("demo", ("/usr/bin/demo",), (EffectKind.FILE,))
before = {"/usr/bin/demo": observed(b"v1", "demo", 0o755)}
after = {"/usr/bin/demo": observed(b"v2", "demo", 0o755)}
safe = derive_mutation_graph(before, after, transaction_id=TX, declaration=safe_declaration)
decision = evaluate_admission(safe)
check("known package update with unchanged authority follows normal path", decision.outcome is AdmissionOutcome.ALLOW and decision.promotion_authorized)

different_content = derive_mutation_graph(before, {"/usr/bin/demo": observed(b"v3", "demo", 0o755)}, transaction_id=TX, declaration=safe_declaration)
check("mutation graph identity binds exact file content", different_content.graph_id != safe.graph_id)

reordered = derive_mutation_graph(dict(reversed(list(before.items()))), dict(reversed(list(after.items()))), transaction_id=TX, declaration=safe_declaration)
check("mutation graph identity is deterministic", reordered.graph_id == safe.graph_id and reordered.canonical() == safe.canonical())

service_path = "/usr/lib/systemd/system/demo.service"
service_decl = CandidateDeclaration("demo", (service_path,), (EffectKind.SYSTEM_SERVICE,))
service = derive_mutation_graph({}, {service_path: observed(b"[Service]", "demo")}, transaction_id=TX, declaration=service_decl)
check("declared new system service requires review", evaluate_admission(service).outcome is AdmissionOutcome.REVIEW)
check("exact reviewed graph can become a known-safe silent transition", evaluate_admission(service, known_safe_graph_ids=(service.graph_id,)).outcome is AdmissionOutcome.ALLOW)

sudo_path = "/etc/sudoers.d/demo"
sudo = derive_mutation_graph({}, {sudo_path: observed(b"demo ALL=(ALL) ALL", "demo")}, transaction_id=TX, declaration=safe_declaration)
check("undeclared privilege expansion is rejected", evaluate_admission(sudo).outcome is AdmissionOutcome.REJECT)

capability = FileObservation(hashlib.sha256(b"capable").hexdigest(), 0o755, "demo", security_capability="0102")
capability_graph = derive_mutation_graph({}, {"/usr/bin/capable": capability}, transaction_id=TX, declaration=CandidateDeclaration("demo", ("/usr/bin/capable",), (EffectKind.FILE,)))
check("file capabilities are privileged effects", any(item.kind is EffectKind.PRIVILEGE_AUTHORITY for item in capability_graph.effects))
check("undeclared file capability is rejected", evaluate_admission(capability_graph).outcome is AdmissionOutcome.REJECT)

module_path = "/usr/lib/modules/6.18/extra/demo.ko"
module = derive_mutation_graph({}, {module_path: observed(b"module", "demo")}, transaction_id=TX, declaration=safe_declaration)
check("kernel module effect is observable and rejected when undeclared", module.effects[0].kind is EffectKind.KERNEL_MODULE and evaluate_admission(module).outcome is AdmissionOutcome.REJECT)

boot_path = "/boot/EFI/Linux/maho.efi"
boot = derive_mutation_graph({}, {boot_path: observed(b"uki", "demo")}, transaction_id=TX, declaration=safe_declaration)
check("boot-state mutation is observable", boot.effects[0].kind is EffectKind.BOOT_STATE)

hook_path = "/usr/share/libalpm/hooks/demo.hook"
hook = derive_mutation_graph({}, {hook_path: observed(b"hook", "demo")}, transaction_id=TX, declaration=safe_declaration)
check("Pacman hook mutation is observable", hook.effects[0].kind is EffectKind.PACMAN_HOOK)

persistence_path = "/etc/xdg/autostart/demo.desktop"
persistence = derive_mutation_graph({}, {persistence_path: observed(b"desktop", "demo")}, transaction_id=TX, declaration=safe_declaration)
check("startup persistence mutation is observable", persistence.effects[0].kind is EffectKind.STARTUP_PERSISTENCE)


for privileged_path in (
    "/etc/udev/rules.d/90-demo.rules",
    "/usr/lib/sysusers.d/demo.conf",
    "/etc/sysctl.d/90-demo.conf",
    "/etc/dbus-1/system.d/demo.conf",
):
    graph = derive_mutation_graph({}, {privileged_path: observed(b"authority", "demo")}, transaction_id=TX, declaration=safe_declaration)
    check(f"high-authority path is privilege authority: {privileged_path}",
          graph.effects[0].kind is EffectKind.PRIVILEGE_AUTHORITY and evaluate_admission(graph).outcome is AdmissionOutcome.REJECT)

for persistence_path in (
    "/usr/lib/tmpfiles.d/demo.conf",
    "/etc/NetworkManager/dispatcher.d/demo",
    "/usr/lib/systemd/system-generators/demo",
    "/etc/profile",
):
    graph = derive_mutation_graph({}, {persistence_path: observed(b"startup", "demo")}, transaction_id=TX, declaration=safe_declaration)
    check(f"startup execution path is persistence: {persistence_path}",
          graph.effects[0].kind is EffectKind.STARTUP_PERSISTENCE and evaluate_admission(graph).outcome is AdmissionOutcome.REJECT)

for loader_path in (
    "/etc/ld.so.conf.d/demo.conf",
    "/usr/lib/binfmt.d/demo.conf",
):
    graph = derive_mutation_graph({}, {loader_path: observed(b"loader", "demo")}, transaction_id=TX, declaration=safe_declaration)
    check(f"loader/interpreter policy is security boundary: {loader_path}",
          graph.effects[0].kind is EffectKind.LOADER_POLICY and evaluate_admission(graph).outcome is AdmissionOutcome.REJECT)

foreign_path = "/usr/bin/other-package"
override_decl = CandidateDeclaration("demo", (foreign_path,), (EffectKind.FILE,))
override = derive_mutation_graph({foreign_path: observed(b"old", "other")}, {foreign_path: observed(b"new", "demo")}, transaction_id=TX, declaration=override_decl)
check("altering another package file is separately observable", any(item.kind is EffectKind.PACKAGE_FILE_OVERRIDE for item in override.effects))
check("undeclared package-file override is rejected", evaluate_admission(override).outcome is AdmissionOutcome.REJECT)

listener_decl = CandidateDeclaration("demo", ("/usr/bin/demo",), (EffectKind.FILE, EffectKind.NETWORK_LISTENER))
listener = derive_mutation_graph(before, after, transaction_id=TX, declaration=listener_decl, listeners=(ListenerObservation("tcp", "0.0.0.0", 8080),))
check("declared new listener requires review", evaluate_admission(listener).outcome is AdmissionOutcome.REVIEW)

incomplete = derive_mutation_graph(before, after, transaction_id=TX, declaration=safe_declaration, inspection_complete=False)
check("candidate that cannot be inspected sufficiently fails closed", evaluate_admission(incomplete).outcome is AdmissionOutcome.REJECT)

scope_exceeded = derive_mutation_graph(before, after | {"/usr/share/demo/readme": observed(b"docs", "demo")}, transaction_id=TX, declaration=safe_declaration)
check("non-boundary declared scope excess requires review", evaluate_admission(scope_exceeded).outcome is AdmissionOutcome.REVIEW)

check("admission model only authorizes promotion on ALLOW", all(
    evaluate_admission(graph).promotion_authorized == (evaluate_admission(graph).outcome is AdmissionOutcome.ALLOW)
    for graph in (safe, service, sudo, module, override, incomplete)
))

print("ALL GUARDIAN ADMISSION CONTRACT TESTS PASS")
