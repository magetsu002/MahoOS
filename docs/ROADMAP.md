# Roadmap

MahoOS V1 is focused on turning the current desktop into a complete system that
can be installed, updated, admitted, recovered, and tested as one product.

## Proven foundations

- complete Hyprland/Quickshell desktop surfaces and immutable Maho runtime releases
- Guardian observation, containment, incident history, and bounded service recovery
- M3B full-generation Btrfs restore mechanics with `/home` preservation
- R1 independent recovery-kernel execution
- R2 independently trusted SystemGeneration + KernelGeneration selection
- R3 native kernel-only rollback on hardware with exact postboot proof
- dependency-light Guardian Recovery TUI with plan-bound authorization requests
- candidate-first Native Admission V1 with exact mutation-graph promotion authority
- revocation-to-recovery planning for kernel-only, full-generation, or external recovery

These claims are scoped. R3 certifies recovery mechanics, not a hostile boot chain;
Secure Boot/signing hardening remains separate. Native Admission is source- and
contract-complete but still needs production update promotion integration and
hardware acceptance before it is a release boundary.

## Before V1

- integrate Native Admission promotion authority into the production update/activation path
- complete M4B native update hardware certification against a genuine newer coherent Primary kernel generation
- extend the now-wired Guardian Recovery TUI beyond R3 into every native recovery mode without weakening independent recovery authority
- finish unified recovery history/status surfaces and product-facing recovery receipts
- harden signed boot/update authority and define Secure Boot/key lifecycle
- finish Arch/CachyOS packaging, installation flow, and ArchISO image
- extend deterministic build checks from recovery evidence generation into initramfs/update payload assembly where toolchains permit reproducible output
- expand interruption, power-loss, stale-evidence, and hostile-input regression campaigns
- broaden hardware, NVIDIA, suspend/resume, multi-monitor, and failure testing
- finish release packaging, documentation, and final acceptance

## Blocked by external availability

M4B hardware certification remains blocked until CachyOS publishes a real newer
coherent Primary kernel generation. Do not manufacture this proof with partial
upgrades, same-version reinstalls, hidden driver migration, or relaxed package
authority.

## After V1

Planned work after the first stable release includes broader personalization,
Maho Themes, more recovery providers, deeper Guardian diagnosis, and additional
hardware coverage.
