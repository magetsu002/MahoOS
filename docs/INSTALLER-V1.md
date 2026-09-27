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

`maho-installer plan` is deliberately read-only. A new attempt is started with
`--attempt-state PATH`: the command durably creates one private UUIDv4 attempt
record before probing and planning, or reuses the exact record already at that
path. The attempt UUID is the deterministic namespace for the installation,
GPT, LUKS, FAT, and Btrfs identities and is part of the canonical plan digest.
Reinstalling the same source on the same disk with a new attempt state therefore
produces new identities and a new confirmation token.

`maho-installer execute` is a separate root/PolicyKit boundary that accepts only
the exact saved plan ID and `ERASE-MAHO:<plan-sha256>` challenge. Execution is limited to provably
disposable loop-backed media or QEMU virtio disks whose serial begins with
`MAHO-DISPOSABLE-`.

It may:

- inspect one exact device with `lsblk`;
- normalize stable physical identity;
- reject mounted, read-only, non-whole-disk or weakly identified targets;
- describe the intended GPT/VFAT/Btrfs layout and ordered Maho assembly stages;
- emit a plan identity and confirmation challenge.

The planner may not:

- repartition or format a device;
- mount a target;
- install packages;
- mutate EFI/BootOrder;
- enroll Secure Boot keys;
- enable the Prevention Boundary;
- manufacture SystemGeneration/KernelGeneration trust;
- grant mutation authority by itself.

The read-only planner therefore reports the explicit privilege boundary while
performing no mutation:

```text
execution_authority = root-or-policykit-required
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

The executor journals the exact attempt identity with `OBSERVED` and
`CONFIRMED`, then re-observes and rebuilds the plan with that same identity
immediately before creating GPT. Any path, major:minor, size, sector, serial,
WWN, transport, loop-backing, source, plan, or attempt drift aborts before the
first write. An old or incomplete journal without the attempt identity cannot
resume.

## Storage contract

The V1 planning contract fixes:

- GPT;
- an exactly 4 GiB FAT32 ESP mounted at `/boot`;
- LUKS2 over every remaining usable GPT sector;
- Btrfs inside LUKS2;
- Maho subvolumes `@`, `@home`, `@snapshots`, and `@var_log`.

The plan records logical and physical sector sizes, primary and backup GPT
boundaries, exact inclusive partition LBAs, GPT/partition/LUKS/Btrfs UUIDs,
encryption parameters, the 128 GiB minimum, and the post-staging reserve limit
`max(20 GiB, 15% of usable filesystem space)`. Disk swap, hibernation,
multi-disk installation, and removable targets are forbidden.

The durable execution journal advances only through:

```text
OBSERVED -> CONFIRMED -> GPT_CREATED -> ESP_FORMATTED -> LUKS_CREATED
  -> LUKS_OPENED -> BTRFS_CREATED -> SUBVOLUMES_CREATED -> MOUNTED
```

On restart, every journaled postcondition is independently checked. A mutation
that is ahead of the journal, a changed target, or an unverifiable phase aborts
for manual inspection instead of repeating a destructive command.

## V1 safety rules

The execution layer fails closed unless all of the following remain true at the
mutation boundary:

1. the exact source revision is still the intended V1 candidate;
2. the exact target disk observation still matches the confirmed plan;
3. no target partition became mounted;
4. the concrete partition layout is bound into the plan digest;
5. the 128 GiB minimum and reserve calculation pass;
6. the media is explicitly classified as disposable test media;
7. the key arrives through a root-readable file rather than command arguments;
8. the single journal lock proves one mutation owner.

Physical firmware key enrollment and production Prevention activation remain
separate explicit administrative certification steps.

## Development rule

Build the installer early as a test harness. Polish it late as a product.

Every new installer stage should first be testable against disposable
image/VM-backed storage. Physical-disk mutation is not an acceptable first
integration test.
