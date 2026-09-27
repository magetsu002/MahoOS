# MahoOS V1 pre-installer architecture freeze

Status: **historical pre-installer architecture freeze; gate subsequently met; RC0 exists**

Decision date: 2026-09-25

Baseline source: `09f2eddc91c8480698afe1dcc4493c72f0b1b6b8`

Closure milestone: `v1-preinstaller-rc0` →
`2d138aa930031f63b4c15a9234a11ce69a26f5e3` (2026-09-26)

This is the canonical V1 architecture contract the installer must preserve. It is
not a current execution gate and does not by itself claim final physical release
certification. The original 2026-09-25 gate result is historical; the frozen
architecture decisions below remain authoritative.

## Historical pre-installer freeze vs current V1 product requirements

The pre-installer gate associated with this freeze was later closed and RC0 was
created. The historical certification report remains a point-in-time evidence
record and must not be read as the current blocker list.

Current active V1 lanes are:

- installer + certified first boot
- automatic maintenance/update coordination
- bad-update recovery closure
- production Prevention VM certification after the installer VM exists
- fresh-install reproducibility
- physical Signed Boot/hardware release gates

Verified persistence baseline transitions, production immutable runtime
deployment, and the boot-bound firewall receipt/activation path are no longer
pre-installer blockers. Their fail-closed semantics remain part of the frozen
architecture.

## Frozen V1 architecture

- **Storage:** UEFI/GPT, one explicitly selected non-removable disk, a dedicated 4 GiB FAT32 Maho ESP mounted at `/boot`, and one LUKS2 container holding Btrfs. Btrfs subvolumes are `@`, `@home`, `@snapshots`, and `@var_log`; candidate and previous roots are transaction-named subvolumes, not permanent partitions. V1 has zram swap, no disk swap, and no hibernation. Multi-disk spanning/RAID and removable targets are unsupported. Minimum target size is 128 GiB. Before mutation and before every candidate update, usable free space must remain at least the larger of 20 GiB or 15% after worst-case staging. ENOSPC rejects before activation; it never triggers deletion of a known-good root.
- **Encryption:** LUKS2 encrypts the Btrfs system and home data; the ESP is unencrypted. Password unlock and an exported recovery key are mandatory. TPM unlock is post-V1 and must not be silently enabled. Recovery must unlock with password or recovery key before selecting a generation.
- **Boot:** Limine is the sole Maho bootloader. Normal uses `linux-cachyos`; fallback/recovery uses `linux-cachyos-lts`. Maho writes only its dedicated ESP and Maho entries. Firmware `BootOrder`/`BootNext`, key enrollment, and deletion of foreign entries require explicit user authority. Windows/OEM entries and Microsoft/OEM trust are preserved by default. Each change stages and verifies a BootGeneration before publication.
- **Hardware/kernel:** x86_64 UEFI only. Intel and AMD integrated/discrete graphics use in-tree drivers; NVIDIA is supported only when DKMS builds and verifies for both primary and fallback kernels. Matching headers and applicable Intel/AMD microcode are mandatory. DKMS, initramfs, or firmware failure rejects the generation. Unknown/unsupported GPUs require a preflight stop, not a generic fallback promise.
- **Generation model:** SystemGeneration identifies the root, PackageGeneration, KernelGeneration, immutable runtime, BootGeneration, recovery state, and source transaction. Published live identity under `/var/lib/maho/generations` is canonical. Historical recovery success never promotes current trust.
- **Retention/GC:** retain current plus two previous eligible SystemGenerations; primary and fallback KernelGenerations for each retained system; current plus one last-verified independent recovery generation; update/recovery/security receipts for 90 days and at least the latest 20 completed operations. Never delete the running generation, active transaction, last known-good root/kernel/recovery, unresolved-incident evidence, or key-rotation rollback material. Under pressure, remove failed/untrusted candidates, expired staging, package cache, then oldest ineligible generations. If reserve remains unmet, reject mutation.
- **Packages/updates:** base packages come from signed Arch, CachyOS, and Maho repositories. Exact packages, effects, signatures, source revision and package-generation identity are recorded. AUR is excluded from installation and automatic updates; later AUR work uses the isolated build/admission path and explicit install authority. Package installation is not activation; only postboot verification may mark `HEALTHY`.
- **Runtime:** source or signed packaged provenance builds a content-addressed immutable runtime. Production checkout deployment requires a clean source and same/forward ancestry relative to the current runtime. Dirty, divergent, or older source requires explicit `--development` and is permanently not production-trust-eligible. Switches are atomic, interrupted activation restores the prior verified runtime, and rollback is explicit/auditable. Guardian consumes but cannot create runtime trust.
- **Guardian/trust:** Guardian detects, explains, recovers and verifies. Providers own their evidence; Guardian does not rewrite facts. Missing or stale evidence is `UNKNOWN`. Root privilege alone, command success, package success, and historical proof grant no trust. One exact, identity-bound, expiring mutation owner exists per operation.
- **Recovery:** the smallest eligible known-good state wins: runtime before kernel, kernel before system root. Recovery selection requires intact current evidence and an exact certified executor. `/home` is outside root rollback. Failed verification remains unresolved and loop protection prevents repeated automatic recovery.
- **Prevention:** V1 choice is **B: physical BPF-LSM enforcement ships disabled/inactive**. For V1, PREVENT means Admission and transaction preflight reject unsafe Maho-owned candidates before mutation; it is not a claim of host-wide command interception. The tested Mutation Boundary remains available for future certification and must not be weakened or casually enabled.
- **Signed Boot:** design is frozen, physical trust is not claimed. Per-device keys are distinct from Maho release signing roots. Provisioning is an explicit user/admin ceremony; the installer may stage signed normal/recovery artifacts but reports `SECURE_BOOT_PENDING` until firmware enrollment and first-boot evidence prove BootAuthority and BootEnvironmentIdentity. Rotation retains a bounded prior key/generation; reset or cloned/restored hardware requires reprovisioning. Microsoft/OEM keys remain unless the user explicitly chooses otherwise. `fwupd` changes firmware evidence and therefore requires re-observation.
- **Machine identity:** every install creates a unique installation UUID, `/etc/machine-id`, device key and device-binding record. Release, source, generation, machine and installation identities are distinct. A disk clone or restored image that does not match its device binding enters `REPROVISION_REQUIRED`; it never silently becomes the same trusted machine.
- **Users:** V1 creates one initial UID 1000 desktop user in `wheel`; root password login is locked. Password hashes are handled only by the target system tools; plaintext is never journaled. Sudo and PolicyKit actions remain explicit. Additional Unix users are not forbidden, but multi-seat/multi-user Maho surface ownership is outside V1 certification. Reinstall preserves `@home` only after exact identity match and explicit consent.
- **Network:** installation is offline-capable only with a complete signed release payload. Otherwise all packages and metadata must be downloaded, signature-verified and staged before destructive mutation. Ethernet and NetworkManager Wi-Fi are supported in preflight; captive portals must be resolved before mutation. No unmanifested download is allowed after disk mutation begins.
- **Firewall:** Maho owns only `table inet maho_host`. A privileged transaction applies and verifies it. The unprivileged UI must consume a root-published receipt bound to boot ID, policy hash and freshness, and report active/certified/stale/unavailable/unknown. Direct netlink failure is never healthy.
- **Installer authority:** a resumable installer journal is the sole coordinator. Each phase has one writer and exact disk, installation, effect, process and expiry authority. Destructive confirmation is bound to the re-observed disk identity. The installer never reboots, edits firmware order, enrolls keys, or preserves home implicitly.
- **Certified first boot:** install completion remains `PENDING` until an explicit reboot verifies expected root/filesystem, SystemGeneration, KernelGeneration, PackageGeneration, runtime, boot artifacts, Guardian, recovery, user/home, network basics and session. Only an identity-bound durable receipt may publish `INSTALLATION_HEALTHY`. It uses the same generation/trust model as updates.

## Explicit V1 limitations

- No hibernation, multi-disk install, removable target, BIOS/CSM, ARM, multi-seat certification, TPM auto-unlock, automatic AUR installation, or active production BPF-LSM enforcement.
- Physical Secure Boot enrollment and trust are not yet certified; current status must remain `UNKNOWN`/pending.
- Full-disk encryption, reinstall-with-home-preservation, installer resume/abort, and certified first boot remain active V1 installer/fresh-install requirements until their certification closes. Retention GC is implemented as an identity/dependency planner plus journaled executor and has an adversarial fixture matrix; production Prevention VM certification remains an active lane once the installer VM exists.
- Hardware support is bounded to devices passing exact preflight. “Linux supports it” is not a certification result.

## Deferred post-V1

TPM-sealed unlock, hibernation, multi-disk/RAID, removable installs, broader multi-user surface ownership, production BPF-LSM enforcement, and reproducible bit-for-bit release claims are post-V1 work.

## Installer invariants

These must be machine-tested:

1. Re-observed target disk identity equals the confirmed identity immediately before the first write.
2. No live/current generation is published before all constituent identities and durable receipts verify.
3. No package transaction, runtime switch, boot publication or recovery has more than one writer.
4. No authority is accepted outside its operation, effects, targets, process identity, parent transaction or expiry.
5. Stale/missing evidence is `UNKNOWN`; no historical receipt promotes current trust.
6. `/home` is neither formatted nor rolled back without an exact, explicit preservation/replacement decision.
7. Running, last-known-good, active-transaction and unresolved-incident state is never garbage-collected.
8. A dirty/regressing runtime cannot become production trust; an explicit development runtime remains visibly trust-ineligible.
9. Package success is not generation activation; installation success is not `INSTALLATION_HEALTHY`.
10. No automatic reboot, firmware mutation, key enrollment, foreign boot-entry deletion, fail-open fallback or hidden destructive retry.

## Certification status

At the 2026-09-25 freeze point, the installer start gate was still closed. That
statement is historical. The closure work subsequently landed and
`v1-preinstaller-rc0` was created at
`2d138aa930031f63b4c15a9234a11ce69a26f5e3`.

The report at `docs/reports/v1-preinstaller-certification-2026-09-25.md` is
intentionally preserved as historical certification evidence; its old blocker
language does not override current main or the active V1 product requirements
listed above.
