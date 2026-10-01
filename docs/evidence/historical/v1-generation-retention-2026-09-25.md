> **HISTORICAL EVIDENCE**
>
> This document records point-in-time certification or design history.
> It is not current project status and does not override current source or canonical architecture documentation.

# V1 generation retention and GC implementation evidence — 2026-09-25

## Source

- Branch: `feat/v1-generation-retention-gc`
- Implementation commit: `7bde200638b83158adbd49ec99a9cf6cefd2770d`
- CI integration commits: `979cd8fbdb6f185140a54e06366e56e78df9b8c1`, `489cdf1ca463e87dc39ac1fb2f22108012a3056a`
- Base: `da17b7a86866fb2cad9247f6f2739e2f569e0082`

## Result

The local generation-retention matrix passed 53 assertions. It covers current
plus two previous eligible SystemGenerations, shared dependencies, current
root/running kernel, active candidate/update/recovery authority, the only and
last independently verified recovery routes, unresolved incidents, rotation
rollback material, audit evidence, deterministic pressure ordering, reserve
refusal, stale/corrupt/wrong identity, partial targets, repeated execution,
ENOSPC and read-only journal publication, ENOSPC receipt publication, and
interruptions before/after metadata commit and physical deletion.

The complete local core contract suite passed with the GC matrix included.
Focused update suites also passed:

- update preparation: 26 assertions
- normal update lifecycle: 13 assertions
- external artifact handoff: 12 assertions
- update adversarial campaign: 27 assertions
- durable setup lifecycle: all contracts passed

An exact committed package was built successfully from implementation commit
`7bde200638b83158adbd49ec99a9cf6cefd2770d`. Package SHA-256:

`1ff949ae11b7be4ab6b8f46314978a2f93c252025afe7c02df192f8f94bededb`

It contains the GC command and both Python modules, as well as the already
merged firewall observer service/timer.

## Transaction invariant

GC first publishes a durable plan carrying exact object identities and the
source inventory digest. It then atomically commits the target inventory before
removing object bytes. Thus an interruption may leave safe, unreferenced bytes
for resume, but cannot leave authoritative generation metadata referring to
content that GC already removed.

## Live read-only observation

The pre-GC physical generation store was successfully adapted without root. It
resolved the current SystemGeneration and 23 dependency objects, reported all
681,728,543 observed bytes protected, zero reclaimable bytes, and sufficient
free reserve. The adapter deliberately disables destructive mutation when an
older installation has no durable GC inventory.

## Remaining certification boundary

This report is implementation and local fault-matrix evidence. The complete
final-source destructive VM campaign must still exercise GC together with the
runtime, persistence, firewall, Vesktop, update, recovery, and compound-failure
scenarios before the installer-start verdict.
