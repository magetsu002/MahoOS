# Agent 5: Secure Boot, measured boot and TPM2 unlock integration

Status (2026-11-06): **source-level policy gate only; physical certification pending**. This document does not authorize any device mutation or override the installer/update transaction owners. It records new user acceptance requirements, including TPM2 auto-unlock, which conflict with the historical 2026-09-25 V1 architecture freeze that deferred TPM auto-unlock. Agent 0 must reconcile the release scope explicitly; do not silently edit or reinterpret the historical freeze.

## Existing authority, not a new boot manager

- `maho_boot_authority.py` owns exact BootGeneration/BootAuthority identities, release sequence and security epoch.
- `maho_secure_boot.py` owns Limine config integrity, loader sealing and `verify_postboot` trust.
- `maho_boot_publication.py` models transactional boot publication.
- `maho_installer_system.py` generates the initial normal and recovery Limine loaders, authenticated configurations and kernel/initramfs payloads.
- `maho_update_native.py` and Maho Update own exact candidate admission/activation. **Agent 4 remains update mutation owner**; Agent 5 supplies signed boot/unlock preconditions and verification results, not a competing updater.
- Guardian consumes verified evidence, never grants firmware trust or repairs PCR mismatches on its own.

Do not mistake tests of OVMF with isolated variable stores for proof of real firmware trust. Normal and recovery payloads must each have a PE/COFF signature validated by firmware *and* an enrolled Limine config checksum, with all kernel, initramfs and microcode paths hash-bound to that config. No automatic chainload to Windows when Maho fails. Preserve the real Windows Boot Manager, original ESP, Microsoft and OEM `PK`/`KEK`/`db`/`dbx` entries and Windows device-encryption recovery access.

## Confirmed code gap: key continuity

At the inspected repository head, `maho_installer_system.py::_phase_boot_generation_published` generates `/var/lib/maho/installer/.boot-signing.key` and `.boot-signing.crt`, signs initial Limine executables, copies only the certificate to `/etc/maho/boot-signing.crt`, and deletes the private key in `finally`. Its temporary certificate is **not automatically enrolled in firmware `db`**, and the ordinary update path does not demonstrate a device signing provider for subsequent loaders. An `sbverify` result proves cryptographic signature validity relative to a certificate; it does not prove that UEFI firmware trusts that certificate. **Do not promote installer success to Secure Boot readiness.**

Repair belongs within the landed SigningProvider/BootAuthority interface, using one persistent *per-device* signing authority provisioned through an explicit Agent 0 ceremony. Do not silently regenerate a new key when the signer is missing. An offline or hardware-protected private key should not be copied into installed roots, ESP, logs, Git or ordinary update artifacts; support exact, auditable one-mission signing requests. Keep the Maho release-signing root separate. Before publication verify the exact signed normal and recovery loader hashes and firmware `db` authorization, preserve the current known-good signed artifacts, and atomically publish only after every prerequisite passes. Key rotation retains both old and new usable trust paths until the new one has physically booted and recovery has been proven.

## TPM policy and its evidence gate

`lib/maho_tpm_unlock_policy.py` is deliberately **pure**. `evaluate_tpm_unlock` only makes an enrollment *eligibility* decision from preexisting `BootGeneration`, `BootAuthority`, `BootEnvironmentIdentity` and `PostBootResult`, plus independently replayed TPM measurements and recovery evidence. It executes no firmware, TPM, disk or slot command. `proposed_enrollment_argv` is an inspectable plan, not approval or execution. An authoritative host-side verifier must bind each reported Limine event to the actual selected entry and artifact digests, verify PCR event-log replay against TPM SHA-256 PCR values, and establish observation freshness before supplying the gate.

Preliminary binding for **Limine v12 or newer once hardware-proven**: SHA-256 PCRs **7 + 8 + 9**. PCR 7 binds the observed UEFI Secure Boot policy, PCR 8 the selected kernel command line/resource paths, and PCR 9 the Limine configuration and actual loaded kernel/initramfs/module bytes. Current upstream Limine v12 documents the relevant measurements; **older or differently built Limine cannot inherit that proof**. PCR 7 alone is insufficient; default UKI PCR 11 guidance must not be incorrectly applied to Limine Linux-protocol boots. A changed kernel or initramfs changes PCR 9 and must have a pre-authorized new unlock policy. Confirm that normal, fallback and independent recovery measurements differ as intended.

`systemd-cryptenroll --tpm2-device=auto --tpm2-pcrs=...` supports explicit PCR values, permitting planned candidate policies. Normal unlock should use systemd's `sd-encrypt` initramfs path with `tpm2-device=auto`, and require actual TPM support/modules/libraries in **every** signed initramfs. The existing installer writes `crypttab.initramfs` without the TPM option; this must be updated only after TPM enrollment and recovery acceptance are explicitly authorized. Do not create an initramfs with a hardcoded LUKS key. Do not enable auto-unlock simply because TPM exists.

For automatic updates, do **not** bind only to the *current* PCR 9 value and hope it survives kernel updates. Use exact offline predicted/replayed measurements for each candidate and recovery selection, ensure token-slot capacity, stage and verify candidate policy coverage **before** publishing the new BootGeneration, retain previous working policy/slots until the new boot passes postboot checks, and only then retire obsolete TPM slots under an exact authorized transaction. If trustworthy PCR prediction, signing, retained slot capacity, recovery support or disk reserve is missing, **defer the update**. Policy signature support for Limine PCRs 8/9 is not implemented here; systemd's common PCR 11/UKI signing flow is not a plug-in replacement. Investigate and certify a signature-based policy only after proving the actual firmware and Limine measurements.

The `require_generation_unlock_coverage` helper requires evidence for current normal, candidate normal, fallback and independent recovery boot roles; the evidence provider and Agent 4 must bind the role to exact BootGeneration, LUKS UUID, expected TPM token, PCR digest set, expiration and provider freshness. A positive boolean alone is not physical proof.

## Recovery and security-change behavior

- **TPM reset/clear, motherboard replacement, firmware key changes, unexpected db/dbx update or PCR drift:** do not attempt blind re-enrollment. Manual LUKS passphrase or exported recovery key is the fallback; diagnose Secure Boot/firmware state with current read-only evidence, preserve encrypted data and require explicit reprovisioning.
- **Kernel/initramfs update:** stage and sign all normal/recovery artifacts and new measured PCR 9 policies before activation. Keep previous known-good boot and unlock policy. On failed postboot verification, select the exact previous known-good generation; no silent Windows fallback or endless boot retries.
- **Signing key rotation:** old certificate and validated old boot loader remain usable through a bounded transition; no deletion of Microsoft/OEM trust. Rotate/revoke only with explicit Agent 0 ceremony after physical proof.
- **LUKS recovery:** never remove the last working passphrase or offline recovery key. Recovery key must be tested by actually unlocking the target, not merely by detecting a slot. Keep a verified, separately stored LUKS header backup that is not on the ESP or the encrypted root alone.
- **Windows:** check its encryption protectors and recovery-material readiness *before* firmware enrollment or BootOrder changes. If Windows enters BitLocker recovery following firmware changes, use the verified recovery method; do not disable protection casually.
- **Maho fails to load:** firmware should report Secure Boot image rejection or let a human choose independent signed Maho recovery via firmware menu. Do not hide the reason by silently redirecting to Windows. Retain the old firmware entry for diagnosis until the replacement has been physically certified; retirement is a later explicit ceremony.

## Emergency read-only triage, no ceremony required

Linux (only once an authorized Linux environment is available):

```sh
findmnt -no SOURCE,TARGET,FSTYPE,OPTIONS /boot
efibootmgr -v
lsblk -o NAME,PATH,FSTYPE,PARTUUID,UUID,MOUNTPOINTS
sbctl status
sbctl verify
ls /sys/class/tpm/
tpm2_pcrread sha256:7,8,9
cryptsetup luksDump /dev/disk/by-partuuid/REPLACE_WITH_VERIFIED_LUKS_PARTUUID  # read-only: exclude secret material from logs
```

Windows, in an administrator PowerShell/terminal (inspection only):

```powershell
Confirm-SecureBootUEFI
Get-Tpm
bcdedit /enum firmware
manage-bde -status C:
manage-bde -protectors -get C:
```

**Never paste a Windows BitLocker recovery key, LUKS recovery key, LUKS header, private signing key or TPM secret into a chat/log/repository.** Record only redacted readiness and fingerprints. These commands are not substitutes for live observation here; the remote computer was offline when this work was prepared.

## Agent 0 physical ceremony: ordered gates, no assumed authorization

1. Confirm Windows still boots, record its current firmware identity and BitLocker/Device Encryption recovery readiness privately; verify at least one accessible recovery method. Record both ESP identities and exact disk target. Make offline backups and test LUKS passphrase/recovery key and header recovery on a safe copy. No deletion/mutation yet.
2. Inventory firmware `BootCurrent`, `BootOrder`, `BootNext`, `db`, `dbx`, `PK`, `KEK`, current Maho and obsolete Arch paths; verify all EFI signatures and enrolled trust. Preserve Microsoft/OEM keys. Record actual installed Limine version and config discovery behavior, including removable fallback aliases.
3. Stage **both** signed normal and signed independent recovery loaders on the exact dedicated Maho ESP under an authorized boot-publisher transaction. Verify enrolled config checksum, all BLAKE2B-bound resources, signer fingerprint, loader signature and matching `db` trust. Preserve old known-good state. Do not overwrite the Windows ESP or boot manager.
4. Request a **separate explicit user ceremony** to enroll the specific per-device certificate or change a firmware entry as necessary, after Windows recovery validation. Prefer a one-time manual firmware boot-menu selection for first test; no autonomous BootOrder/BootNext changes. If Maho fails, stop and record the firmware error rather than silently changing Windows.
5. Cold boot explicitly into Maho with Secure Boot enforced. Independently establish the executed loader path/signature, config integrity, selected primary kernel/initramfs, TPM event log and PCRs; verify LUKS manual recovery first. Confirm Maho desktop after postboot health checks. Boot Windows and confirm its encrypted drive protection remains healthy.
6. With explicit LUKS-header mutation authority, enroll TPM policies for tested normal, fallback and recovery paths, verifying capacity and retaining password/recovery slots. Test auto-unlock in a separately approved physical boot. Force an authorized PCR mismatch and confirm the expected manual passphrase/recovery fallback, without clearing TPM or removing recovery slots.
7. Test signed update staging/activation to a new kernel, candidate policy coverage, postboot activation and rollback. Test cold boot normal, independent fallback/recovery, Windows cold boot, invalid EFI signature refusal, config/kernel/initramfs tamper refusal, TPM reset **simulation** (never actual TPM clear without a separate ceremony), and old still-signed loader/replay detection. Log device-specific proof without secrets.
8. Only after repeated physical proof and a separate explicit authorization, retire the misleading obsolete firmware entry and consider any boot order adjustment. Do not alter other firmware entries or trust material.

## Agent 4 update integration contract

Agent 4 should call the **existing** Signed Boot publisher to request an exact signed normal/fallback/recovery BootGeneration for each kernel update, with signed loader/config/loaded-resource hashes, per-device signing authority, verified ESP identity, release sequence/security epoch, and retained previous generation. Use this Agent 5 policy gate as an additional *pre-activation* dependency:

- `candidate_boot_signed_and_firmware_trusted`: cryptographically and operationally proven from signed publication receipts (no hash-only shortcuts).
- `measured_boot_candidate_pcrs`: exact PCR 7/8/9 values derived by an independently verified measured-boot replay, bound to selected Limine version, mode, config and artifacts.
- `luks_policy_coverage`: exact current/candidate/fallback/recovery token/policy bindings, sufficient capacity, previous slots retained; no auto-enroll without exact authorization.
- `initramfs_unlock_support`: `sd-encrypt` and correct TPM2 cryptsetup libraries/binaries in both candidate normal/fallback/recovery initramfs.
- `postboot_verified`: measured actual PCR replay, actual unlocked LUKS identity, actual signed loader and generation + Guardian health; only then mark generation `HEALTHY`.
- Any absent/stale/dissenting provider evidence => `PENDING` or `ATTENTION_REQUIRED`; don't silently weaken requirements, bypass the boot publisher, reboot or fall back to Windows.

## Acceptance / evidence levels

| Evidence | Status as of this document |
| --- | --- |
| Existing Signed Boot virtual proof | Historical 13/13 isolated OVMF campaign, exact head must be checked before reuse |
| New TPM policy source validation | Focused pure Python positive/negative tests (not hardware testing) |
| Existing signer continuity across package updates | **UNPROVEN / blocker** |
| Current physical Secure Boot db + ESP + firmware entries | **UNKNOWN / bridge offline** |
| Windows encryption recovery material | **UNKNOWN / must verify privately** |
| Limine v12 PCR 8/9 measured boot on this laptop | **UNKNOWN** |
| TPM2 token enrollment / unlock / failed PCR recovery | **NOT PERFORMED** |
| Physical Maho+Windows dual-boot acceptance | **NOT PERFORMED** |

Upstream technical references:
- Limine v12 Secure Boot and Measured Boot: https://github.com/limine-bootloader/limine/blob/v12.x/USAGE.md
- systemd TPM2 enrollment and PCR-signed policy: https://www.freedesktop.org/software/systemd/man/latest/systemd-cryptenroll.html
- Arch systemd-cryptenroll integration and recovery notes: https://wiki.archlinux.org/title/systemd-cryptenroll
