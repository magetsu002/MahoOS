# MahoOS V1 pre-installer certification report — 2026-09-25

Verdict: **NOT READY FOR INSTALLER**

This report is evidence for the architecture-freeze candidate, not a release certification. No installer was started, no host storage or firmware was mutated, no key was enrolled, and no reboot or destructive physical test was performed.

## Exact source and workspace

- Observed `origin/main`: `09f2eddc91c8480698afe1dcc4493c72f0b1b6b8`.
- Campaign worktree: `/home/magetsu/Projects/Maho-OS-preinstaller-freeze`.
- Campaign branch: `feat/preinstaller-architecture-freeze`, based exactly on that main revision.
- Protected TUI worktree `/home/magetsu/Projects/Maho-OS-system-tui-v1-polish` was read-only and untouched.
- The primary checkout was stale at `dcea6e3c584c9d7ae95c46e3b0f07c97c921c48e`, 38 commits behind main, and had a local Vesktop edit. It was not reset, cleaned, or modified.

## Physical read-only baseline

- Boot ID: `0f8533ba-5016-46e5-b9cb-73e55adbd1a1`; kernel: `7.2.5-1-cachyos`.
- Root: Btrfs filesystem `ce979d1c-c145-4be0-9ce3-591b6fd0a3a1`, subvolume `@`; separate `@home`, `@var_log`, and snapshot mounts. Btrfs device error counters were zero.
- Root had about 50 GiB available. The 4 GiB FAT ESP was 78% used with about 936 MiB available.
- Live publication verified SystemGeneration `gen-22f047c31d21d39d400212f80e2b20b71da4e63da31fb236748e8cd553644aa7`, KernelGeneration `kgen-ea592a185e09104d2fdd33818108303b26bd8e7c801840d172ccd8b1a1ad01eb`, PackageGeneration `pkg-2edc0ea7f4abd9bf66decdd4b6f0687057e30d477daf9d89428085a63092d624`, root subvolume UUID `6c1473c2-60fa-984d-a49b-11c7458d57be`, previous root `a7a682fe-1f34-5d4e-b912-1f9720b7aebb`, and recovery generation `g3-623c64a36c689d4d23c82130` for transaction `upd-20260924T185307Z-8c9c00b0dbc9` in `HEALTHY` state.
- Both `linux-cachyos` 7.2.5 and `linux-cachyos-lts` 6.18.50 had matching headers and NVIDIA 580.178.04 DKMS modules.
- No failed system or user units were observed. Core Maho user units and the graphical session target were active. Guardian self-health was `HEALTHY`; required providers were fresh.
- Guardian severity was L1 for two Limine autostart files. Exact old/new package extraction and `pacman -Qkk` proved these changes were the legitimate `limine-snapper-sync` 1.31.0 → 1.32.0 package effect; the incident was not suppressed or cleared.
- Signed Boot remained `UNKNOWN`: firmware Secure Boot was disabled/setup mode. Limine booted successfully, but no physical enrolled-key trust proof existed.
- Prevention enforcement was disabled/inactive, matching its documented physical boundary.
- Unprivileged firewall inspection returned insufficient netlink visibility and correctly remained unusable, not healthy.
- Vesktop was installed as `vesktop-bin 1.6.7-4` under `/opt/vesktop`. Main still expected `/usr/lib/vesktop`; the observed “could not build bounded runtime” was a confirmed package-layout regression. A correct `/opt/vesktop` edit exists only in the unrelated dirty primary checkout and was deliberately not copied or claimed.
- Listener review found Vesktop only on loopback port 6463, plus pre-existing local development/tunnel listeners and a service on 9993; this campaign did not establish ownership/trust for the non-Maho listeners.

## Runtime regression root cause and fix

The live `runtime/current` manifest named stale source `dcea6e3`; `runtime/previous` named current main `09f2edd`. Filesystem timestamps align the switch with `bin/maho-setup install` from the stale primary checkout immediately after its local Vesktop edit. The old setup recorded source revision and content hash but had no Git cleanliness check, ancestry check, or downgrade authority. A dirty checkout could therefore deploy bytes whose manifest named only its HEAD.

The campaign adds a fail-closed deployment planner:

- production checkout deployments require clean Git state;
- production transitions must be same-revision or forward descendants;
- Git-less packaged payloads require explicit `release.json` provenance;
- dirty, older, divergent, or unrelated checkout deployment requires `--development`;
- development runtimes remain content-verifiable but are marked not production-trust-eligible;
- Guardian reports such a runtime as `DEGRADED`, never `VERIFIED`;
- existing atomic activation and verified automatic rollback remain intact.

Current main already contains the canonical live-publication reader. Running that source against the host resolved the exact current generation. The user-facing unresolved generation was entirely due to the stale deployed runtime, not a second generation store.

## Exact-source verification completed

- `git diff --check`: pass.
- Focused runtime deployment, runtime release, Guardian trust/live-state, and durable setup transaction suites: pass.
- Full `tests/core-contracts.sh`: pass on clean commit `c8c612d34399f787d2b31d531c46720b8fb8c3af`.
- Arch package build: pass; package release provenance names that exact commit and contains the new deployment planner.
- Disposable QEMU/OVMF Signed Boot: 13/13 pass with isolated variable stores, including valid normal/recovery chains, invalid/wrong signer, config/kernel/initramfs/microcode tamper, damaged normal/recovery, replay, and revoked generation. The durable summary is `v1-preinstaller-qemu-signed-boot-2026-09-25.json`.
- Full destructive Maho VM torture campaign: not rerun on this commit.

## Performance and quality baseline

These are observations, not targets:

| Measure | Observed |
|---|---:|
| Firmware | 9.647 s |
| Bootloader | 1.144 s |
| Kernel | 0.997 s |
| Initrd | 4.149 s |
| Userspace to graphical target | 8.314 s |
| Total firmware to graphical target | 24.253 s |
| User manager to default target | 0.442 s |
| Largest boot service outlier | NetworkManager wait-online, 5.428 s |
| `maho status --json` | 0.34 s |
| `maho-guard status --json` | 0.20 s |
| `maho-trust status --json` | 0.04 s |
| `maho-firewall status --json` | 0.06 s, unusable visibility |

The three Quickshell Maho UI processes used approximately 250 MiB, 234 MiB, and 178 MiB RSS at the sample. Service-cgroup accounting showed large totals for security and shell cgroups, but those include child processes and are not a clean idle-memory attribution. Detection/recovery, suspend/resume, battery, shutdown/reboot, first-frame, and full update-phase timings were not re-measured on final source.

## Product value audit

| Candidate | Core/frequency/severity value | Retrofit cost | Risk/testability | Decision |
|---|---|---|---|---|
| Runtime anti-regression authority | Very high; confirmed live trust regression | High after installer | Bounded and adversarially testable | **Implemented now** |
| Certified first boot | Very high; prevents “install command succeeded” from becoming false health | Very high | Objective identity/postcondition contract | **Architecture selected; implementation belongs to installer work after gate** |
| Resumable installer journal | High for power/process failure | Very high | Phase/fault-injection testable | **Architecture selected; implementation belongs to installer** |
| Encryption | High and extremely expensive to retrofit | Extreme | Standard LUKS2, but recovery needs destructive certification | **V1 encrypted layout selected** |
| Retention/GC | High operational value | High | ENOSPC/fault-injection testable | **Policy selected; implementation/certification blocker** |
| Signed Boot provisioning | High trust value | High | High firmware risk, objectively testable | **Design selected; physical certification pending** |
| Production BPF prevention | Distinctive, but high failure blast radius | Medium | Extensive VM tests exist; physical parent authority incomplete | **Explicitly disabled for V1** |
| Firewall status receipt | Frequent and trust-relevant | Medium | Boot/freshness/policy-hash testable | **Selected; implementation blocker** |
| Package-attributed persistence transition | High signal quality; confirmed false-positive-like L1 | Medium | Exact package/transaction/hash tests possible | **Selected; implementation blocker** |
| Generic EDR/AV/MAC/app sandbox | Outside Maho V1 promise | High | Broad and risky | **Rejected for V1** |

## Final-source destructive certification matrix

`NOT_COVERED` here means not rerun against this campaign’s final commit. Older torture evidence remains historical evidence only. Every requested scenario has one classification.

| Area | Scenario | Classification | Evidence |
|---|---|---|---|
| Boot | normal boot | NOT_COVERED | No reboot authorized |
| Boot | fallback kernel | NOT_COVERED | No reboot authorized |
| Boot | recovery boot | NOT_COVERED | No reboot authorized |
| Boot | corrupted normal boot | RECOVERED_AUTOMATICALLY | QEMU selected trusted recovery when normal was damaged |
| Boot | corrupted recovery boot | PREVENTED | QEMU refused damaged recovery loader |
| Boot | stale boot artifact | PREVENTED | QEMU modeled replay/revocation as non-current trust, never VERIFIED |
| Boot | mismatched initramfs | PREVENTED | QEMU refused initramfs hash mismatch |
| Boot | wrong kernel | PREVENTED | QEMU refused kernel hash mismatch |
| Boot | boot metadata drift | PREVENTED | QEMU refused config tamper/missing enrollment |
| Runtime | immutable runtime corruption | DETECTED_ONLY | Setup status rejects payload hash drift |
| Runtime | runtime deployment interruption | RECOVERED_AUTOMATICALLY | Setup transaction contract restores exact previous runtime |
| Runtime | stale runtime deployment | PREVENTED | Production ancestry test rejects downgrade |
| Runtime | runtime rollback attempt | PREVENTED | Normal path rejects; explicit development path is trust-ineligible |
| Runtime | runtime owner death | NOT_COVERED | No kill/fault campaign on final source |
| Runtime | runtime integrity observer death | NOT_COVERED | No final-source fault campaign |
| Guardian | provider death | NOT_COVERED | Unit tests only; no final-source destructive campaign |
| Guardian | Guardian death | NOT_COVERED | No final-source destructive campaign |
| Guardian | stale evidence | DETECTED_ONLY | Focused live-state tests preserve UNKNOWN/stale semantics |
| Guardian | corrupted evidence | NOT_COVERED | No full campaign rerun |
| Guardian | missing evidence | DETECTED_ONLY | Focused live-state tests preserve UNKNOWN semantics |
| Guardian | journal flooding | NOT_COVERED | No final-source stress run |
| Guardian | simultaneous subsystem failures | NOT_COVERED | No final-source stress run |
| Guardian | recovery-loop protection | NOT_COVERED | No full campaign rerun |
| Guardian | verification failure | NOT_COVERED | Setup subcase covered, general matrix not rerun |
| Session/UI | compositor death | NOT_COVERED | Physical session not disrupted |
| Session/UI | shell death | NOT_COVERED | Physical session not disrupted |
| Session/UI | Notify failure | NOT_COVERED | No final-source fault run |
| Session/UI | Dock failure | NOT_COVERED | No final-source fault run |
| Session/UI | Link failure | NOT_COVERED | No final-source fault run |
| Session/UI | Files failure | NOT_COVERED | No final-source fault run |
| Session/UI | wallpaper failure | NOT_COVERED | No final-source fault run |
| Session/UI | clipboard failure | NOT_COVERED | No final-source fault run |
| Session/UI | simultaneous surface failure | NOT_COVERED | No final-source fault run |
| Session/UI | graphical dependency failure | NOT_COVERED | No final-source fault run |
| Session/UI | login/session startup race | NOT_COVERED | No logout/reboot campaign |
| Update | dependency solving | NOT_COVERED | No final-source VM run |
| Update | package download failure | NOT_COVERED | No final-source VM run |
| Update | staging interruption | NOT_COVERED | No final-source VM run |
| Update | package mutation interruption | NOT_COVERED | No final-source VM run |
| Update | candidate drift | NOT_COVERED | No final-source VM run |
| Update | Admission reject | NOT_COVERED | No final-source VM run |
| Update | Admission allow | NOT_COVERED | No final-source VM run |
| Update | authority replay | NOT_COVERED | No final-source VM run |
| Update | candidate mount failure | NOT_COVERED | No final-source VM run |
| Update | kernel update | NOT_COVERED | Historical M4B only |
| Update | header mismatch | NOT_COVERED | No final-source VM run |
| Update | DKMS failure | NOT_COVERED | No final-source VM run |
| Update | initramfs failure | NOT_COVERED | No final-source VM run |
| Update | activation interruption | NOT_COVERED | No final-source VM run |
| Update | reboot in each durable phase | NOT_COVERED | No final-source VM run |
| Update | postboot mismatch | NOT_COVERED | No final-source VM run |
| Update | successful HEALTHY transaction | NOT_COVERED | Historical M4B only |
| Recovery | runtime recovery | RECOVERED_AUTOMATICALLY | Focused setup activation rollback contract |
| Recovery | SystemGeneration recovery | NOT_COVERED | No final-source VM run |
| Recovery | KernelGeneration recovery | NOT_COVERED | No final-source VM run |
| Recovery | corrupt previous root | NOT_COVERED | No final-source VM run |
| Recovery | missing recovery generation | NOT_COVERED | No final-source VM run |
| Recovery | executor death before mutation | NOT_COVERED | No final-source VM run |
| Recovery | executor death after mutation | NOT_COVERED | No final-source VM run |
| Recovery | failed verification | DETECTED_ONLY | Setup contract retains unresolved incident |
| Recovery | power interruption | NOT_COVERED | No final-source VM run |
| Prevention | direct destructive command | NOT_COVERED | Historical VM evidence only |
| Prevention | Python | NOT_COVERED | Historical VM evidence only |
| Prevention | opaque binary | NOT_COVERED | Historical VM evidence only |
| Prevention | shell indirection | NOT_COVERED | Historical VM evidence only |
| Prevention | namespace path | NOT_COVERED | Historical VM evidence only |
| Prevention | protected process signal | NOT_COVERED | Historical VM evidence only |
| Prevention | expired authority | NOT_COVERED | Historical VM evidence only |
| Prevention | wrong process identity | NOT_COVERED | Historical VM evidence only |
| Prevention | wrong executable | NOT_COVERED | Historical VM evidence only |
| Prevention | wrong target | NOT_COVERED | Historical VM evidence only |
| Prevention | break glass | NOT_COVERED | Historical VM evidence only |
| Prevention | ordinary development workload unaffected | NOT_COVERED | Historical VM evidence only |
| Storage | ENOSPC | NOT_COVERED | No final-source VM run |
| Storage | read-only state | NOT_COVERED | No final-source VM run |
| Storage | low-space update | NOT_COVERED | No final-source VM run |
| Storage | low-space recovery | NOT_COVERED | No final-source VM run |
| Storage | metadata persistence failure | NOT_COVERED | No final-source VM run |
| Storage | power loss during durable publication | NOT_COVERED | No final-source VM run |
| Storage | generation GC boundaries | NOT_COVERED | Policy only; implementation not certified |

## Concrete blockers

1. Exact healthy package-transaction authority cannot yet advance the persistence baseline, so the legitimate Limine package change remains an active L1.
2. No privileged boot-bound firewall receipt publisher feeds the unprivileged product status; current live firewall state is unavailable.
3. The confirmed Vesktop `/usr/lib` → `/opt` package-layout fix is not on a clean reviewed branch/main, and current main remains broken for a fresh build.
4. The full destructive system VM matrix above has not been rerun on the final campaign source; only the 13-scenario QEMU/OVMF Signed Boot subset is current.
5. Physical Signed Boot, fallback/recovery boot, and key provisioning remain unproven; current host trust is correctly `UNKNOWN`.
6. Retention/GC and storage-pressure behavior are policy only and lack implementation plus ENOSPC/power-loss certification.
7. Final campaign source has not passed PR CI, landed on main, been deployed through the canonical production path, or converged with the live runtime (local core/package/QEMU checks pass).
8. The requested complete performance baseline, especially recovery/detection/update phases, suspend/resume, battery and first-frame quality, has not been captured on final source.

No release tag was created. Installer work must not begin while these blockers remain.
