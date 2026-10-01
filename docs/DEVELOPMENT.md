# Development

This document is the practical build/test/package manual. Architecture belongs in [ARCHITECTURE.md](ARCHITECTURE.md), ownership in [COMPONENTS.md](COMPONENTS.md), and contribution policy in [CONTRIBUTING.md](../CONTRIBUTING.md).

## Environment

MahoOS is developed primarily for Arch-based Linux, but many contract tests also run in clean CI containers.

Dependencies vary by lane. The authoritative machine-readable references are the workflow files under `.github/workflows/` and `packaging/arch/PKGBUILD.in`. Common native development dependencies include Git, Bash, Python, CMake, Ninja, Qt 6, KDE KIO, Clang/libbpf for prevention work, and the platform tools required by the subsystem being tested.

Do not install or enable privileged system components merely to run a unit test.

## Repository checks

Start with:

```bash
git status --porcelain=v1 -b
git diff --check
```

For shell changes:

```bash
bash -n path/to/script
```

For Python changes:

```bash
python -m py_compile path/to/module.py
```

## Core contracts

The broad local contract entry point is:

```bash
bash tests/core-contracts.sh
```

Many subsystems also have focused tests. Run the narrow tests for the changed owner first, then the broader contract suite appropriate to the change.

Examples:

```bash
python tests/test_maho_installer_plan.py
python tests/test_maho_installer_execute.py
python tests/test_maho_installer_s12.py

python tests/test_maho_update_state.py
python tests/test_maho_mutation_authority.py
python tests/test_guardian_reliability.py
```

Do not substitute a neighboring test for the exact changed path.

## Maho Files

Maho Files is a Qt 6/KIO application. A focused native build is:

```bash
cmake -S apps/maho-files -B build/maho-files -G Ninja   -DMAHO_FILES_BUILD_TESTS=ON
cmake --build build/maho-files
ctest --test-dir build/maho-files --output-on-failure
```

Its file/device operations depend on KIO/Solid; do not replace those dependencies with test-only production logic.

## Desktop diagnostics

On an installed/development Maho environment:

```bash
maho-shell status --json
maho-shell doctor
maho-shell logs 120
```

User-service diagnostics can also use:

```bash
systemctl --user status maho-shell.service
journalctl --user -u maho-shell.service
```

These commands observe the installed/runtime state. They do not prove that an arbitrary checkout is deployed.

## Runtime setup and convergence

The durable setup tool exposes:

```bash
bash bin/maho-setup preflight
maho-setup status
```

`maho-setup install` mutates the user's installed Maho runtime and must not be used casually on a daily-driver machine. Development deployment is explicit and remains production-trust-ineligible by design.

When a claim depends on the running system, verify source, deployed runtime, service wiring, and the relevant subsystem evidence after deployment. Source tests alone are not runtime convergence.

## Arch package

The package build entry point used by CI is:

```bash
bash tools/build-arch-package.sh "$PWD/dist"
```

Run this in a suitable Arch build environment with the package dependencies available. Package validation should inspect the payload/provenance and, when appropriate, install it only in a disposable test environment.

## VM and physical testing

Use disposable VM tooling for destructive installer, update, recovery, prevention, and boot tests. A VM test is not physical certification.

Physical testing must be explicit about the machine, boundary, destructive effects, and proof captured. Never convert a historical physical result into a claim about current source without rerunning the required verification.

Evidence-level definitions are canonical in [CONTRIBUTING.md](../CONTRIBUTING.md).
