# Roadmap

MahoOS is Pre-V1. This roadmap describes direction, not a live task board.

## Pre-V1

The Pre-V1 phase is about convergence:

- make a fresh install assemble the same architecture that development systems use;
- harden update, recovery, generation, Guardian, and prevention boundaries under interruption and failure;
- converge installer, first-boot, boot, runtime, and release provenance;
- prove supported hardware and physical trust boundaries honestly;
- finish the public contributor/security/release foundations needed for a real project rather than a single development machine.

Pre-V1 does not promise interface stability.

## V1

V1 should be an installable, supportable MahoOS release with a bounded hardware/support statement and a coherent path for:

- the Maho desktop and platform integrations;
- current-evidence Guardian/reliability status;
- candidate-based system updates;
- exact recovery and generation retention;
- certified first boot;
- explicit security/prevention boundaries;
- boot and recovery identities that fail closed when trust cannot be proven.

V1 should preserve user control: destructive storage actions, firmware/key changes, reboot/shutdown decisions, and exceptional authority remain explicit.

## Later

Post-V1 work may expand:

- hardware coverage;
- richer Maho Settings and App Resolver experiences built on existing platform authorities;
- printing UX over CUPS;
- TPM-sealed unlock and stronger pre-kernel freshness mechanisms;
- hibernation;
- multi-disk/RAID and broader storage layouts;
- broader multi-user/multi-seat certification;
- additional prevention and recovery coverage;
- deeper personalization without weakening the authority model.

Architecture remains canonical in [ARCHITECTURE.md](ARCHITECTURE.md); this roadmap should not duplicate it or become a temporary blocker list.
