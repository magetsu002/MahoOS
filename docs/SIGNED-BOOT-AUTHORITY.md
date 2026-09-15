# MahoOS signed boot authority

Status: source contracts and isolated QEMU/OVMF certification complete;
physical firmware enrollment and hardware certification are not performed.

## Trust chain

MahoOS keeps three identities separate:

1. `BootGeneration` identifies the exact loader, configuration, Primary/LTS
   kernels and initramfs images, microcode, authenticated command line, and
   independent recovery artifacts. Every digest names its algorithm and
   purpose. SHA-256 Maho identities and Limine BLAKE2B integrity suffixes are
   not interchangeable.
2. `BootAuthority` records why one generation is allowed: the device signer,
   Maho release authority, release sequence, security epoch, policy versions,
   recovery authority, and source revision. Changing a signer does not change
   a kernel identity, and changing a kernel does not silently rotate a signer.
3. `BootEnvironmentIdentity` records what firmware presented. Unknown EFI
   variables, the actual executed image, the boot entry, or the ESP remain
   explicit missing evidence. `/boot` is never assumed to be the booted ESP.

Guardian may report `HEALTHY` only when the complete postboot proof succeeds.
`SecureBoot=1` by itself grants no trust.

## Limine construction

The only supported construction order is clean Limine EFI, exact config,
BLAKE2B hashes on every loaded resource, config checksum enrollment, bounded
Maho metadata, EFI signing, independent PE/signer/checksum/content verification,
then transactional publication. Signed bytes are immutable.

Normal and recovery use separate loader and config identities:

```text
EFI/MahoOS/Normal/limine.efi
EFI/MahoOS/Normal/limine.conf
EFI/MahoOS/Recovery/limine.efi
EFI/MahoOS/Recovery/limine.conf
```

Limine 12.8 still searches multiple case-insensitive locations and accepts an
SMBIOS Type 11 `limine:config:` string before disk configuration. V1 therefore
records that discovery surface and requires inspection to prove that the only
disk candidate is the loader-owned config. SMBIOS configuration must be absent.
An alternate candidate, stale signed EFI image, duplicate loader, or ambiguous
ESP fails closed. The legacy `limine-snapper-sync` path remains recovery input
only; it cannot write a trusted config or issue signed activation authority.
Snapper provides snapshots, Guardian decides eligibility, and Maho reseals a
current generation.

## Replay and rollback

Release sequence is monotonic and independent of wall-clock time. Security
epoch revokes an entire unsafe trust era. A cryptographically valid artifact
from an earlier epoch remains untrusted, and Guardian revocation is never
cleared by signature validity.

Rollback selects an older still-eligible `SystemGeneration`, then builds a new
`BootGeneration` under the current epoch and authority. It does not restore an
archived loader as authority.

V1 has an unavoidable pre-kernel limitation: standard UEFI Secure Boot with a
long-lived trusted `db` certificate can authenticate an older correctly signed
Limine binary restored by an offline attacker. Release sequence and epoch are
enforced postboot, so Guardian refuses `HEALTHY`, activation authority, and
trusted evidence, but firmware may execute that loader before Guardian runs.
Complete pre-kernel freshness needs an independently reviewed mechanism such as
a minimal Maho Boot Gate with rollback-resistant epoch storage. That component
is intentionally not implemented until its key storage, update, recovery, and
power-loss semantics can be certified.

## Keys

Per-device Secure Boot keys and the Maho release root are separate. Installed
machines carry public release trust only. TPM-backed material can prevent key
extraction, but does not prevent an authorized privileged process from asking
the TPM to sign unless stronger TPM policy or user authorization is configured.
TPM clear, firmware reset, or motherboard replacement produces an explicit
`reprovision-required` state; continuity is never fabricated.

Normal rotation retains old trust through `rotation-dual-trust`, seals and
boots a new generation, requires postboot proof, and only then retires the old
authority. Compromise uses a separate reprovision path.

Future enrollment must inventory PK, KEK, db, dbx, firmware defaults,
Microsoft/OEM certificates, Option ROM needs, Windows and firmware utilities,
and fwupd. No enrollment strategy is assumed portable across machines.

## Virtual certification

`maho-secure-boot inspect` and `inventory` are read-only. The QEMU harness uses
one disposable OVMF variable store per scenario and never attaches host disks.
The fixture builder creates test-only keys, enrolls only copied OVMF stores,
seals and signs clean Limine images, creates bounded FAT ESP images, and boots a
minimal initramfs that emits an exact serial receipt. Negative cases require
positive refusal evidence: OVMF `Access Denied`, a Limine config checksum panic,
or the exact Limine BLAKE2B URI mismatch. A timeout alone cannot pass.

The certified matrix covers signed normal and recovery boot, tampered and
wrong-signer loaders, changed and unenrolled configs, kernel/initramfs/microcode
tamper, independent recovery after normal-loader damage, damaged recovery,
old-generation replay, revocation, and every virtual publication interruption.
Run it with:

```text
bash tests/qemu-secure-boot-certification.sh /tmp/maho-secure-boot
```

The replay scenario proves the documented limitation rather than hiding it: an
old correctly signed loader executes before the kernel, then the current
release-sequence/security-epoch model refuses trusted postboot state. The
revoked-generation scenario likewise reaches only an `UNTRUSTED` receipt.

Physical firmware mutation, production EFI publication, reboot, and real M4B
activation remain prohibited. Virtual certification does not authorize hardware
provisioning or constitute hardware certification.
