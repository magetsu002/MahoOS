# Installer and boot architecture

This document owns the detailed installer/storage/boot contract. Global authority/trust semantics are canonical in [ARCHITECTURE.md](../ARCHITECTURE.md), and generation/update relationships are in [updates-recovery.md](updates-recovery.md).

## Principle

The installer assembles existing MahoOS architecture. It does not create an installer-only recovery, update, trust, boot, or security model.

A successful install command is not an accepted installation. Installation remains pending until certified first boot proves the expected installed identity.

## V1 storage contract

The bounded V1 architecture is:

- x86_64 UEFI;
- GPT on one explicitly selected non-removable target disk;
- a dedicated 4 GiB FAT32 Maho ESP mounted at `/boot`;
- LUKS2 for the remaining Maho system/data container;
- Btrfs inside LUKS2;
- subvolumes `@`, `@home`, `@snapshots`, and `@var_log`;
- zram swap rather than disk swap;
- no V1 hibernation;
- no V1 multi-disk/RAID or removable-target installation;
- minimum 128 GiB target;
- pre-mutation reserve requirement of at least the larger of 20 GiB or 15% of usable filesystem space after worst-case staging.

Running/known-good/recovery state is not deleted to make an unsafe installation or update fit.

Password unlock and an exported recovery key are part of the V1 encryption/recovery contract. TPM auto-unlock is not silently enabled.

## Exact target and destructive confirmation

The installer must observe stable target identity and bind the plan before the first write.

The plan includes the physical target identity, source/release identity, concrete layout, generated filesystem/container identities, and ordered effects. Destructive confirmation is bound to that whole plan, not just a display path such as `/dev/nvme0n1`.

Immediately before mutation the target is re-observed. Identity/layout drift aborts before the write.

The installer never treats an old confirmation as permission for a different disk, source, layout, or install attempt.

## Transaction journal

One installer journal coordinates durable progress and one phase writer owns each mutation.

Storage phases advance only after their postcondition is durable. A representative storage sequence is:

```text
OBSERVED
→ CONFIRMED
→ GPT_CREATED
→ ESP_FORMATTED
→ LUKS_CREATED
→ LUKS_OPENED
→ BTRFS_CREATED
→ SUBVOLUMES_CREATED
→ MOUNTED
```

On resume, completed postconditions are re-observed. If mutation is ahead of the journal, target identity changed, or a phase cannot be verified, the installer stops for explicit recovery/inspection rather than replaying destructive commands.

Secrets such as the encryption credential must not be placed in command arguments or durable plaintext journals.

## System assembly

After storage, the installer assembles the already-defined MahoOS system:

```text
verified payload
→ base system/repositories
→ primary + fallback kernels
→ boot/recovery artifacts
→ generation identities
→ immutable Maho runtime
→ platform/user services
→ desktop/login wiring
→ first boot
```

The installer must not manufacture Guardian trust, generation health, or Prevention authority simply because files were copied successfully.

## Certified first boot

Initial SystemGeneration identity binds the observed Btrfs subvolume UUID, rather than only the subvolume name. The immutable initial root manifest also binds the filesystem UUID, exact boot artifact hashes, BootGeneration, installation attempt, source revision, and recovery identity. First-boot publication checks these bindings before promoting trust. Publication checksums alone cannot authorize new claims. Legacy initial manifests without these bindings remain unresolved until independently recertified; a reader must not silently rewrite their identities or reuse historical acceptance as current proof.

The installation remains pending across reboot.

Certified first boot re-observes the installed machine and proves the expected relationships, including the relevant:

- installation/machine identity;
- root/LUKS/Btrfs/subvolume identity;
- `SystemGeneration` / `PackageGeneration` / `KernelGeneration`;
- immutable Maho runtime/provenance;
- boot artifacts / `BootGeneration`;
- recovery route;
- initial user/home relationship;
- required system services and Guardian evidence;
- security/platform state required by the accepted install contract.

Only a durable identity-bound result may publish installation acceptance. Failure keeps the install pending/unresolved; the certifier does not silently repair arbitrary mismatches.

## BootGeneration, BootAuthority, BootEnvironmentIdentity

Boot trust keeps three concepts separate.

### BootGeneration

Identifies exact boot material: loader/config, primary/fallback kernels and initramfs, microcode, authenticated command-line/config relationships, and independent recovery artifacts.

### BootAuthority

Records why a BootGeneration is allowed: signer/release authority, release sequence/security epoch, policy relationships, recovery authority, and source/generation linkage.

Changing a signer does not silently change a kernel identity; changing a kernel does not silently rotate trust.

### BootEnvironmentIdentity

Records what firmware actually presented/executed: EFI variables, boot entry/image, ESP, and other required observations.

`/boot` is never assumed to be the booted ESP merely because it is mounted there.

Guardian may report boot trust only when the required postboot proof succeeds. `SecureBoot=1` alone is not enough.

## Limine and publication

MahoOS uses Limine as the V1 bootloader.

Normal and recovery boot identities are independent. Boot publication is transactional: exact config/resources are hashed, the accepted metadata/authority is bound, signing/verification occurs in the required order, and publication only proceeds when the resulting artifact identities are known.

Alternative/stale loader/config discovery paths must not silently become trusted boot input.

Maho writes its own dedicated boot state. Foreign Windows/OEM entries and Microsoft/OEM trust are preserved unless the user explicitly authorizes a change.

## Signed Boot keys

Per-device Secure Boot keys and the Maho release-signing authority are separate concepts.

Physical key enrollment is an explicit user/admin ceremony. The installer may stage the artifacts needed for that ceremony, but it must not silently enroll keys, rewrite firmware boot order, delete foreign entries, or claim physical trust before firmware and first-boot evidence prove the environment.

Normal key rotation keeps a bounded prior trust path until the new generation boots and verifies. Firmware reset, TPM clear where relevant, motherboard replacement, or a cloned/restored machine that no longer matches its device binding enters reprovision-required state rather than fabricating continuity.

## Pre-kernel freshness limit

Standard UEFI Secure Boot with a long-lived trusted `db` certificate can authenticate an older correctly signed loader restored by an offline attacker.

Maho's release sequence/security epoch can detect that situation after the kernel starts and refuse current trust/activation, but that does not stop firmware from executing the old still-signed loader first.

Complete pre-kernel freshness requires a separately reviewed rollback-resistant mechanism (for example a future minimal boot gate). That mechanism is not part of the current architecture until its key storage, update, recovery, and power-loss behavior is independently designed and certified.

## User-control boundary

The installer/boot path must never hide:

- destructive target-disk mutation;
- reboot or shutdown;
- firmware BootOrder/BootNext mutation;
- Secure Boot key enrollment/removal;
- deletion of foreign boot entries;
- home preservation/replacement decisions.

Explicit authority is required for each such boundary. Convenience does not override recoverability.
