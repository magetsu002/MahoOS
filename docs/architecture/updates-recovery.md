# Updates, generations, and recovery

This document owns the detailed update/recovery/generation lifecycle. Trust and authority semantics are canonical in [ARCHITECTURE.md](../ARCHITECTURE.md).

## Ownership

**Maho Update owns MahoOS system-update mutation.**

Package tools may execute package operations inside the accepted transaction, but no second updater may independently mutate the live system and later ask Maho to bless the result.

Automatic AUR installation is forbidden. AUR artifacts, when supported, must remain outside automatic system-update authority unless a future architecture review explicitly changes that rule.

## Generation identities

Maho separates related identities so one successful check cannot silently stand in for another.

### PackageGeneration

Identifies the package state relevant to the system generation and its transaction/provenance relationship.

### KernelGeneration

Identifies the primary/fallback kernel state and the kernel-critical relationships required by the accepted system.

### BootGeneration

Identifies exact boot artifacts and their boot authority. BootGeneration is detailed in [installer-boot.md](installer-boot.md).

### SystemGeneration

Binds the accepted root/system identity to the relevant package, kernel, runtime, boot, recovery, and source-transaction relationships.

A directory name or snapshot timestamp is not sufficient generation identity.

## Candidate lifecycle

Updates are prepared away from the currently accepted root.

The architecture separates:

1. **discovery and plan** — determine the intended package/effect set;
2. **candidate preparation** — create the bounded candidate and bind it to the current base;
3. **candidate mutation** — perform the package/system mutation only inside that candidate;
4. **admission and verification** — inspect the exact result/effects and reject unsupported drift;
5. **recovery preparation** — ensure an eligible recovery route exists before activation;
6. **activation authority** — bind the exact candidate/base/generation/effects to the only allowed activation path;
7. **reboot/handoff** — remain explicit; preparing an update does not silently reboot the user;
8. **postboot verification** — prove the expected root, package/kernel/boot/runtime/recovery relationships on the new boot;
9. **acceptance** — only verified postboot state may become the accepted current generation.

Package success is not activation. Root exchange is not health. Boot is not acceptance.

Missing, stale, replayed, wrong-target, or expired authority must fail before mutation/activation where possible and remain unresolved afterward otherwise.

## Interruption

Every durable phase must be restart-safe.

Before activation, a failed candidate can be discarded without making it current. After a root switch, recovery must be able to identify the exact previous eligible state. An interrupted transaction may leave cleanup work, but it must not leave authoritative metadata pointing at deleted/unidentified state.

No recovery loop should repeatedly apply the same failed automatic action without new evidence/authority.

## Recovery rule

**The smallest eligible known-good state wins.**

Preferred scope:

```text
runtime recovery
    ↓ if insufficient
kernel recovery
    ↓ if insufficient
system-root / SystemGeneration recovery
```

Recovery selection requires current evidence about the failure and an exact known provider. It does not search for a random command that appears capable of changing the symptom.

`/home` is outside system-root rollback. User data is not silently rolled back as a side effect of system recovery.

After recovery, verification is required. A recovery command returning zero is not proof that the incident is resolved.

## Recovery state and eligibility

A recovery route is eligible only when its required artifacts and identity relationships remain intact and the route is allowed by current policy.

Historical success can support eligibility history, but historical proof never promotes current trust by itself. Current boot/root/runtime evidence still matters.

## Retention

Retention is an identity/dependency policy, not a directory-age policy.

The V1 contract retains:

- the current `SystemGeneration`;
- the two newest previous eligible `SystemGeneration` identities;
- the primary and fallback `KernelGeneration` dependencies of retained systems;
- the current and one last independently verified recovery generation;
- required update/recovery/security receipts for at least the bounded audit window defined by policy.

Hard protections include:

- the running generation/root/kernel;
- any active update/recovery transaction;
- the last known-good root/kernel/recovery route;
- unresolved-incident evidence;
- key-rotation rollback material still required by policy.

A protected identity is never deleted to satisfy free-space pressure.

## Garbage collection

Generation GC plans against an exact source inventory and object identities.

Pressure reclamation order is:

1. abandoned failed/untrusted candidates;
2. expired staging state;
3. disposable package cache;
4. oldest superseded **ineligible** generations.

If the safe reserve still cannot be restored, mutation remains blocked. The system does not trade away its only known recovery route for free space.

The GC transaction commits authoritative target inventory before deleting bytes. Interruption may leave unreferenced bytes for later cleanup, but must not leave authoritative metadata pointing at content already deleted.

Missing references, corrupt inventory, stale plans, changed object content, or an unverifiable dependency fail closed.

## Update/recovery relationship with Guardian

Guardian consumes update/recovery evidence and may identify that a known recovery path is required. It does not become the package executor or invent a new mutation path.

Maho Update/recovery providers own their transaction facts. Guardian verifies the resulting evidence and keeps unresolved state visible when the proof is insufficient.

## User-visible automation boundary

MahoOS may automate bounded preparation and verified recovery, but it must not hide:

- reboot or shutdown;
- firmware/key enrollment;
- destructive user-disk operations;
- authority expansion;
- automatic AUR installation.

The architecture should reduce babysitting by making safe work deterministic, not by silently taking control away from the user.
