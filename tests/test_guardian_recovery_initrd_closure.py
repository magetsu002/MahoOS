#!/usr/bin/env python3
from __future__ import annotations
import ast, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK = ROOT / "config/mkinitcpio/install/sd-maho-guardian-recovery-r3"
LIB = ROOT / "lib"

def check(name: str, ok: bool) -> None:
    if not ok: raise AssertionError(name)
    print("PASS", name)

def included_python_modules() -> set[str]:
    text = HOOK.read_text()
    modules = {m.group(1) for m in re.finditer(r'add_file\s+"\$MAHO_R3_SOURCE_ROOT/lib/([A-Za-z0-9_]+)\.py"', text)}
    loop = re.search(r'for name in ([^;]+); do\s*\n\s*add_file "\$MAHO_R3_SOURCE_ROOT/lib/\$name"', text)
    if loop:
        modules.update(pathlib.Path(item).stem for item in loop.group(1).split() if item.endswith('.py'))
    return modules

def local_imports(module: str) -> set[str]:
    path = LIB / f"{module}.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name.split('.', 1)[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module.split('.', 1)[0]]
        else:
            continue
        for name in names:
            if (LIB / f"{name}.py").is_file(): found.add(name)
    return found

def main() -> None:
    included = included_python_modules()
    roots = {"guardian_r3_native_verify", "guardian_recovery_tui", "guardian_recovery_r3", "guardian_recovery_r3_executor"}
    check("R3 initrd declares all executable Python roots", roots <= included)
    pending = list(sorted(roots)); required = set(roots)
    while pending:
        current = pending.pop()
        for dep in sorted(local_imports(current)):
            if dep not in required:
                required.add(dep); pending.append(dep)
    missing = sorted(required - included)
    check("R3 initrd Python dependency closure is complete", not missing)
    check("R3 initrd closure includes generation and trust primitives", {"guardian_offline_recovery", "maho_generation_v2", "maho_kernel_generation", "maho_trust_identity"} <= required)
    unrelated = included - required
    check("R3 initrd has no accidental local Python dependency expansion", not unrelated)
    print("R3 INITRD MODULES", ",".join(sorted(required)))
    print("ALL GUARDIAN RECOVERY INITRD CLOSURE TESTS PASS")

if __name__ == "__main__": main()
