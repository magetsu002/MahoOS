# MahoOS architecture

This is the canonical architecture entry point for MahoOS.

The central rule is:

> **System truth, presentation, observation, and mutation are different responsibilities.**

MahoOS tries to make Linux easier to operate without replacing the authorities that already own real platform state or granting a component power merely because it can observe a problem.

## MahoSystem and MahoShell

### MahoSystem

**MahoSystem** is the system/reliability domain.

It gathers bounded status from existing subsystems, translates those contracts into a common product vocabulary, and exposes reliability, trust, update, recovery, security, and diagnostic state to Maho surfaces.

MahoSystem is **not** a monolithic mutation daemon and is not a second database of Linux truth. The underlying subsystem payloads and mutation owners remain authoritative. For example, Guardian owns its evidence model, Maho Update owns update transactions, and NetworkManager still owns network state.

### MahoShell

**MahoShell** is the desktop/session presentation domain.

It contains the visible system surfaces and controls that a user interacts with. It may request operations from the correct owner, but presentation does not become authority merely because a control exists in the shell.

The detailed desktop/platform contract is in [desktop-platform.md](architecture/desktop-platform.md).

## Observation and mutation

An **observer** measures or reads state. A **mutation owner** performs a bounded change.

Those roles stay separate whenever practical.

```text
observer → evidence → decision
                       │
                       ▼
              exact mutation owner
                       │
                       ▼
                  verification
```

Seeing a failure does not grant permission to repair it arbitrarily. A known recovery provider may act only inside its accepted target/effect/authority boundary. Unknown failure remains visible instead of becoming an invented repair command.

## Health and trust

**Health** answers whether the system or component is operating as expected.

**Trust** answers whether Maho has current, sufficient evidence that the relevant state may be relied on for a trust-sensitive decision.

They are related but not interchangeable. A service can be running while its trust evidence is missing. A historically certified generation can exist while the current boot identity is unresolved.

Core invariants:

- **UNKNOWN != healthy**
- **stale evidence != healthy**
- **missing evidence != healthy**
- **health != trust**
- **historical proof != current trust**

No success exit code, package installation result, signature alone, or old certification silently promotes current trust.

## Root and authority

Root is Linux privilege. Maho authority is a narrower claim.

**root != authority**

A Maho mutation authority is expected to be:

- exact about the intended operation;
- bounded to specific effects and targets;
- scoped to the parent transaction or reason for change;
- tied to the acting process/identity where required;
- short-lived or explicitly consumable;
- attributable in durable evidence.

Privilege may be necessary to perform an operation, but privilege alone does not prove that the operation is authorized by MahoOS.

## Guardian

Guardian consumes provider evidence, correlates current state, explains reliability/security findings, selects known recovery paths, and verifies outcomes.

Guardian does not rewrite provider facts to make the system look healthy. Missing or stale required evidence remains unresolved. Guardian self-health is also distinct from the health of the machine it is observing.

A prevented mutation is evidence about a prevented action; it is not automatically proof that the machine is compromised.

## Generations

MahoOS models recoverable system identity through related generations rather than treating the current filesystem tree as enough truth.

The major identities are:

- **PackageGeneration** — the exact package state relevant to the system generation;
- **KernelGeneration** — the primary/fallback kernel and related boot-critical kernel state;
- **BootGeneration** — exact boot artifacts and their boot authority;
- **SystemGeneration** — the root/system identity that binds the relevant package, kernel, runtime, boot, recovery, and transaction relationships.

Generation identity is explicit. Retention is dependency/eligibility based, not a directory-age policy.

See [updates-recovery.md](architecture/updates-recovery.md) and [installer-boot.md](architecture/installer-boot.md).

## Update and recovery

Maho Update owns system-update mutation.

The architectural path is:

```text
discover → plan → candidate → mutate candidate → admit/verify
         → prepare recovery → authorize activation → explicit reboot/handoff
         → postboot verification → accepted generation
```

Package installation is not activation, and booting a candidate is not acceptance.

Recovery chooses the smallest eligible known-good state that can correct the proven failure: runtime before kernel, kernel before system root. It uses an exact recovery provider and verifies the result. It does not guess.

Automatic AUR installation is forbidden. AUR work, when present, remains isolated from automatic system update authority.

Detailed lifecycle and retention rules are in [updates-recovery.md](architecture/updates-recovery.md).

## Prevention

Maho prevention separates convenience from enforcement.

Intent Guard may identify deterministic interactive intent for early feedback. It is **not** the security boundary.

The Mutation Boundary enforces accepted protected effects against exact targets/process identities and exact authority. Break-glass is bounded and audited; it is not a global off switch.

See [prevention-security.md](architecture/prevention-security.md).

## Installer and boot

The installer assembles existing Maho architecture; it does not create a separate trust model.

Installation binds an exact target and destructive plan before mutation, journals durable phases, builds the boot/recovery/generation state, and remains pending until certified first boot verifies the installed identity.

Signed Boot separates artifact identity, authority, and observed firmware environment. Firmware Secure Boot being enabled is not by itself trusted postboot evidence.

See [installer-boot.md](architecture/installer-boot.md).

## External platform authorities

MahoOS integrates with Linux authorities instead of cloning them.

Examples include NetworkManager, BlueZ, KIO/Solid, PipeWire/WirePlumber, XDG `.desktop`/MIME/portal contracts, Secret Service, PolicyKit, and CUPS when printing is implemented.

The canonical ownership/path table is [COMPONENTS.md](COMPONENTS.md).

## Fail-safe behavior

The fail-safe rule is: **when required evidence or authority is insufficient, do less.**

MahoOS must not hide reboot, shutdown, firmware mutation, key enrollment, destructive user-disk behavior, or an authority expansion behind a convenience path.

Recovery and automation are valuable only when they remain narrower than the failure they are trying to solve.

## Engineering completion

MahoOS distinguishes engineering stages explicitly:

```text
SOURCE → TEST → MERGE → DEPLOY → CONVERGE → VERIFY → ACCEPT
```

Source being correct does not prove that a running machine uses it. Merge does not prove deployment. Deployment does not prove convergence. A runtime-sensitive claim needs runtime verification at the appropriate evidence level.

The evidence levels and contributor workflow are defined in [CONTRIBUTING.md](../CONTRIBUTING.md).
