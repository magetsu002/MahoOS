# MahoOS V1 pre-installer closure — 2026-09-20

This is the final pre-installer gate. No installer or ArchISO work was started. The machine-readable authority is [v1-preinstaller-closure-2026-09-20.json](./v1-preinstaller-closure-2026-09-20.json).

## Outcome

The V1 architecture is ready to enter the installer phase with two truthful external blockers and a bounded set of physical campaigns. Guardian runtime recovery is physically certified. The AUR normal-update handoff is implemented and has a real verified `ani-cli 5.1-1` candidate. Missing current generation and boot authority remain visible as `UNKNOWN`; no boolean or historical evidence was used to conceal them.

| Area | Status | Exact reason |
|---|---|---|
| Source/runtime convergence | CLOSED | The final report-only revision is deployed and verified after commit without restarting the graphical session. |
| Normal update authority | READY_FOR_AUTHORIZED_PHYSICAL_CERTIFICATION | The cloc authority is valid history but stale for current source. No harmless canonical repository version transition exists, and the installed root campaign requires administrator authentication. The source-bound model remains unchanged because Maho has no independent signed release authority yet. |
| AUR flow | READY_FOR_AUTHORIZED_PHYSICAL_CERTIFICATION | The public receipt handoff now revalidates artifact identity, proves zero repository dependency mutation, routes by effects, reuses Guardian Admission and normal execution, and writes the existing update receipt. `ani-cli 5.1-1` is prepared; live preflight waits for current root campaign deployment and normal recertification. |
| Adaptive | CLOSED | A1–A16 and integration/adversarial contracts pass; the service is active with zero restarts. |
| Guardian | CLOSED | Detection, explanation, causality, containment, recovery, freshness, and self-health are closed. Overall trust remains correctly `UNKNOWN` because generation and boot authority are absent. |
| Guardian runtime recovery | CLOSED | Physical campaign `runtime-recovery-20260920T185413Z-eeabdaa906e5` passed exact corruption, incident, separate proposal/authorization, rollback, verification, resolution, receipt retention, and forensic release retention. |
| Kernel recovery | EXTERNALLY_BLOCKED | #41 is open. Canonical Maho repositories still contain exactly the installed Primary/LTS kernels and headers. The apparent `7.2.6-1` update is AUR-only and cannot be used to manufacture M4B proof. |
| Full-generation recovery | READY_FOR_AUTHORIZED_PHYSICAL_CERTIFICATION | R1/R2/R3, target selection, bounded authorization, executor, postboot proof, and mode-neutral TUI contracts pass. A new physical rollback needs genuine SystemGeneration lineage, root, and reboot. |
| Generation authority | EXTERNALLY_BLOCKED | This installation predates exact transaction-bound publication. Its missing transaction/provenance cannot be reconstructed without fabricating authority; the next genuine M4B generation must publish it. |
| Signed Boot | READY_FOR_AUTHORIZED_PHYSICAL_CERTIFICATION | Source and VM proof are closed. Live proof is absent, Secure Boot is disabled, SetupMode is enabled, and the ESP must be checked first. |
| Secure Boot physical certification | READY_FOR_AUTHORIZED_PHYSICAL_CERTIFICATION | Key enrollment and postboot proof require the physical firmware campaign after ESP health is established. |
| Firewall | READY_FOR_AUTHORIZED_PHYSICAL_CERTIFICATION | Namespace and transactional contracts pass. Four live connectivity contexts require root and a controlled emergency rollback session. |
| Memory | CLOSED | zram and systemd-oomd are active; reliability and pressure contracts pass. |
| Storage | READY_FOR_AUTHORIZED_PHYSICAL_CERTIFICATION | Btrfs reports no scrub errors and has about 84 GiB free, but no completed scrub statistics exist. The ESP logged an unclean FAT unmount and needs offline `fsck.fat`. |
| SDDM/session | READY_FOR_AUTHORIZED_PHYSICAL_CERTIFICATION | Login, portals, keyring, audio, and Maho services are healthy. A deliberate relogin/session teardown was not forced. |
| Networking | READY_FOR_AUTHORIZED_PHYSICAL_CERTIFICATION | Wi-Fi and NetworkManager are live; deliberate loss/recovery belongs to the controlled connectivity campaign. |
| VPN/ZeroTier | READY_FOR_AUTHORIZED_PHYSICAL_CERTIFICATION | Both daemons are active and the ZeroTier interface exists. Mullvad connected/disconnected and coexistence transitions remain physical evidence. |
| Recovery history | CLOSED | One mode-neutral read-only surface now validates runtime plus R3 records, retains malformed evidence, and never converts history into current trust. |
| Open GitHub issues | EXTERNALLY_BLOCKED | [#41](https://github.com/magetsu002/MahoOS/issues/41) awaits a canonical coherent Primary kernel generation. |
| Blank-disk installer/ArchISO | INSTALLER_PHASE | Deliberately excluded; no implementation was started. |

## Physical evidence obtained

- Runtime recovery receipt: `/home/magetsu/.local/state/maho/certification/runtime-recovery/runtime-recovery-20260920T185413Z-eeabdaa906e5.json`
- Exact recovery authority: `recovery-auth-7f8ef9c6df27c5f0569cc085`
- Existing recovery receipt: `recovery-receipt-5a8db4e79c399bcbe41956be`
- AUR candidate receipt: `/home/magetsu/.local/state/maho/security/aur-builds/build-97745866466975aa0c13.json`
- `ani-cli` transition: `5.0-1 -> 5.1-1`, AUR commit `a26ced7308b4ceb2867444b55032eea6db86eda7`, artifact SHA-256 `3121de83a8f5896698ca7007f1e983971c94e528fab85815aebdd9debdf345b4`
- Zero failed system units and zero failed user units; ten managed Maho services active with zero restarts.
- NetworkManager, Mullvad, ZeroTier, PipeWire, WirePlumber, portals, Secret Service, zram, systemd-oomd, and SDDM active.
- Intel `i915` and NVIDIA `580.178.04` drivers active; internal display at 2560×1600@240 Hz; Bluetooth audio active.

## Authority decisions

The normal-update authority lifecycle was deliberately not weakened. The current schema binds the complete source revision, machine, execution profile/effects, Guardian graph, roots, exact package transition, and verification. Replacing source identity safely requires an independent signed Maho release authority plus a versioned updater implementation/profile identity. Neither exists yet, so an unrelated source change continues to invalidate authority fail-closed.

The live SystemGeneration/KernelGeneration was not synthesized. Existing schemas require an exact transaction, package/kernel provenance, root identity, runtime identity, and boot artifact relationships. The running pre-authority installation has no legitimate historical transaction record containing all of those facts.

## Worktree audit

- `maho-m3b-hardening`: still valuable, but its boot-promotion campaign assumes persistent Primary default and is unsafe to port after R3 until boot authority is normalized.
- `Maho-OS-guardian-completion`: superseded by main.
- `Maho-OS-guardian-signedboot-work`: superseded by main.
- `Maho-OS-ui-motion-live`: evidence worth preserving; two uncommitted Link/Notify QML motion edits are outside this no-redesign campaign.
- `MahoOS-guardian`: experimental visual/lock work outside this closure scope.

No historical worktree was cleaned, reset, deleted, or blindly cherry-picked.

## Verification

The complete `tests/core-contracts.sh` suite passed. Focused runtime-recovery, recovery-history, AUR handoff, M4B payload-closure, and setup contracts also passed. The real AUR build found and closed a previously fixture-hidden Bubblewrap mount bug before producing the verified candidate.

MahoOS can enter the installer phase because every remaining item is now either closed, ready for a specifically bounded physical campaign, externally blocked by facts that cannot be manufactured, or explicitly part of the installer phase. Trust remains fail-closed throughout.
