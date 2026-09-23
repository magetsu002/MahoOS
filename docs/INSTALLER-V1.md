# MahoOS V1 installer contract

The installer assembles already-certified MahoOS subsystems. It is not a new
recovery, update, trust, boot, or security architecture.

## Product path

```text
ISO
  -> preflight
  -> exact disk observation
  -> deterministic install plan
  -> explicit destructive confirmation
  -> partition/filesystem transaction
  -> base system + repositories
  -> Primary/Fallback kernels
  -> Limine
  -> Guardian Recovery
  -> generation authorities
  -> immutable Maho runtime
  -> root/user services + SDDM
  -> first boot
  -> Guardian verification
```

The source revision, exact physical target identity, concrete storage layout and
all destructive effects must be bound before the first mutation. A confirmation
from an older plan must never authorize a different disk, source revision or
layout.

## Current implementation boundary

`maho-installer plan` is deliberately read-only.

It may:

- inspect one exact device with `lsblk`;
- normalize stable physical identity;
- reject mounted, read-only, non-whole-disk or weakly identified targets;
- describe the intended GPT/VFAT/Btrfs layout and ordered Maho assembly stages;
- emit a plan identity and confirmation challenge.

It may not:

- repartition or format a device;
- mount a target;
- install packages;
- mutate EFI/BootOrder;
- enroll Secure Boot keys;
- enable the Prevention Boundary;
- manufacture SystemGeneration/KernelGeneration trust;
- grant an execution authority.

The read-only planner therefore reports:

```text
execution_authority = none
mutation_performed  = false
```

even after a confirmation string has been validated.

## Disk identity

The current plan identity includes the observed target's:

- device path;
- byte size;
- model;
- serial;
- WWN;
- transport;
- logical and physical sector size;
- major:minor identity.

The plan also includes the exact Maho source revision, layout contract, assembly
stages and current blockers. The destructive challenge is derived from the
whole plan identity, not from a display name such as `/dev/nvme0n1`.

Immediately before a future execution layer performs any mutation it must
re-observe the device and rebuild the plan. Any identity or plan drift invalidates
the old confirmation.

## Storage contract

The planning contract currently requires:

- GPT;
- a VFAT ESP mounted at `/boot`;
- Btrfs for the remaining root storage;
- Maho subvolumes `@`, `@home`, `@snapshots`, and `@var_log`.

The current planner intentionally leaves the exact ESP size as an execution-time
policy value. **That means the current read-only confirmation is not yet a
partition-write authority.** Before destructive execution is implemented, the
layout must become concrete (partition boundaries/sizes and identifiers) and the
final destructive authority must bind that concrete layout.

## V1 safety rules

A future execution layer must fail closed unless all of the following remain
true at the mutation boundary:

1. the exact source revision is still the intended V1 candidate;
2. the exact target disk observation still matches the confirmed plan;
3. no target partition became mounted;
4. the concrete partition layout is bound into the execution authority;
5. required installation payloads are locally staged and verified;
6. power/storage prerequisites are satisfied;
7. no unrelated physical disk is writable through the installer;
8. boot, generation and recovery evidence are created from facts produced by
   the new installation rather than copied from another machine.

Physical firmware key enrollment and production Prevention activation remain
separate explicit administrative certification steps.

## Development rule

Build the installer early as a test harness. Polish it late as a product.

Every new installer stage should first be testable against disposable
image/VM-backed storage. Physical-disk mutation is not an acceptable first
integration test.
