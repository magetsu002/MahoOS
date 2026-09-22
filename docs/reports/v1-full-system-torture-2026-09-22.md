# MahoOS V1 full-system torture report

- Mission start: `c873b703d7f9be6eeed255d211e94dd9505d7c07`
- Certified campaign source: `441fa99281dd9fc020029f827339336468aacd3f`
- Ending source before this report commit: `441fa99281dd9fc020029f827339336468aacd3f`
- Campaign evidence: `/home/magetsu/.local/state/maho/certification/vm-torture/20260922T144028Z-441fa99281dd9fc020029f827339336468aacd3f`
- Verdict: **INCOMPLETE / FAIL**
- Distinct scenarios: 21
- Iterations: 52
- Destructive injections: 51

## Source commits

- `441fa99281dd9fc020029f827339336468aacd3f` docs(vm): keep incomplete torture coverage explicit
- `2b6be176ba4955ab9baec4fbf5c1449a62e7baf2` fix(vm): verify wallpaper JSON from provider stream
- `7472bdce17df314996ee81ebdc9177abbaed031c` fix(vm): await wallpaper provider before session torture
- `5b443846855b857c1e63468dd0f47d7ddb028397` test(vm): stream journal flood through one producer
- `ee8c20a360f813f3dce160c24e7ea480b3340a29` fix(vm): start installed Guardian authorities in torture guest
- `80264d641dc599abca5c267070f2462e0cfa0461` test(vm): preserve graphical setup diagnostics
- `cc01021f4524bbc30bad595d184211e3a5d064de` fix(vm): identify dedicated home disk by virtio topology
- `5f3851fcfb1b7e0e03a50d5fa8113384449a4829` fix(vm): allow only read-only QEMU auxiliary media
- `cc14f1dd5fedd50685e1e434e9b9d17cb9df2f36` fix(vm): source torture guest logic before staging
- `c09ec0a6ba3f9cf1dbd8a59fec8cc02c19780398` test(vm): add fail-closed full-system torture harness
## Outcomes

- PREVENTED: 3
- RECOVERED_AUTOMATICALLY: 43
- RECOVERED_WITH_AUTHORITY: 3
- DETECTED_ONLY: 2
- NOT_COVERED: 1
- BUG: 0

## Scenario matrix

| Scenario | Iteration | Expected | Actual | Pass |
|---|---:|---|---|---|
| bounded-ui-failure-storm | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| compound-session-guardian | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| compound-session-guardian | 2 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| compound-session-guardian | 3 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| compound-session-guardian | 4 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| compound-session-guardian | 5 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| compound-session-wallpaper-clipboard | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| guardian-self-kill | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| guardian-self-kill | 2 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| guardian-self-kill | 3 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| guardian-self-kill | 4 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| guardian-self-kill | 5 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| journal-flood-reconciliation | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| stale-guardian-evidence | 1 | DETECTED_ONLY | DETECTED_ONLY | True |
| authority-replay-and-stale-identity | 1 | PREVENTED | PREVENTED | True |
| protected-filesystem-destruction | 1 | PREVENTED | PREVENTED | True |
| protected-process-signal | 1 | PREVENTED | PREVENTED | True |
| scoped-break-glass | 1 | RECOVERED_WITH_AUTHORITY | RECOVERED_WITH_AUTHORITY | True |
| corrupt-recovery-prior | 1 | DETECTED_ONLY | DETECTED_ONLY | True |
| immutable-runtime-corruption | 1 | RECOVERED_WITH_AUTHORITY | RECOVERED_WITH_AUTHORITY | True |
| clipboard-worker-kill | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| quickshell-all-surfaces | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| quickshell-surface-kill | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| quickshell-surface-kill | 2 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| quickshell-surface-kill | 3 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| session-compositor-kill | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| session-compositor-kill | 10 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| session-compositor-kill | 11 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| session-compositor-kill | 12 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| session-compositor-kill | 13 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| session-compositor-kill | 14 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| session-compositor-kill | 15 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| session-compositor-kill | 16 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| session-compositor-kill | 17 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| session-compositor-kill | 18 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| session-compositor-kill | 19 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| session-compositor-kill | 2 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| session-compositor-kill | 20 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| session-compositor-kill | 3 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| session-compositor-kill | 4 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| session-compositor-kill | 5 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| session-compositor-kill | 6 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| session-compositor-kill | 7 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| session-compositor-kill | 8 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| session-compositor-kill | 9 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| wallpaper-provider-race | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| wallpaper-provider-race | 2 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| wallpaper-provider-race | 3 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| enospc-durable-publication | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| readonly-durable-publication | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| update-interruption-contracts | 1 | RECOVERED_WITH_AUTHORITY | RECOVERED_WITH_AUTHORITY | True |
| update-reboot-interruption | 1 | NOT_COVERED | NOT_COVERED | True |

## Host safety

- boot_id_unchanged: True
- root_source_unchanged: True
- source_revision_unchanged: True
- source_clean_after_campaign: True
- prevention_state_unchanged: True
- maho_services_unchanged: True

## Bugs found

- No Maho V1 product bug was demonstrated by the completed scenarios.
- Four torture-harness defects were found and fixed without weakening product assertions: read-only media classification, pre-staging script loading, fresh-user Guardian startup, and wallpaper provider/JSON readiness.

## Session

- 20/20 compositor SIGKILL cycles converged with a new Hyprland process and complete graphical dependencies.
- Shell, dock, and notify recovered individually and together with no duplicate main ownership.
- Clipboard workers and wallpaper provider races converged to the saved wallpaper and a valid generated palette.

## Guardian

- 5/5 Guardian self-kills restarted with renewed heartbeat evidence.
- Persisted healthy evidence became stale and unusable when observation stopped, then refreshed after provider restoration.
- 2,500 benign journal records did not prevent delegated recovery verification and incident closure.

## Runtime and update

- Real installed immutable runtime corruption recovered only through exact single-use authority; the corrupt generation remained preserved.
- A corrupt current plus corrupt prior produced no recovery authority (`DETECTED_ONLY`).
- Update interruption contract/adversarial suites passed; same-disk reboot interruption remains `NOT_COVERED`.

## Prevention and storage

- Protected mutations and signals were denied across direct, Python, opaque binary, alias, and namespace paths.
- Expired/wrong-identity authorities were denied; exact short-lived authorities worked and were evidenced.
- ENOSPC/read-only publication preserved valid durable JSON and resumed after the fault cleared.

## Compound failures

- 5/5 simultaneous Guardian plus compositor failures converged.
- Simultaneous compositor, wallpaper-provider, and clipboard-owner failure converged.
- Eight rapid Notify failures remained bounded and closed without runaway incident growth.

## Performance

- detection_latency_ms: samples=24 min=267ms median=328ms p95=5585ms max=5739ms
- recovery_latency_ms: samples=42 min=2251ms median=8323ms p95=9266ms max=48161ms
- convergence_latency_ms: samples=42 min=2251ms median=8323ms p95=9266ms max=48161ms
- worst outlier: bounded-ui-failure-storm iteration 1 at 48161ms

## Required coverage not yet demonstrated

- same-disk reboot during AWAITING_RECOVERY_AUTHORIZATION/RECOVERING/VERIFYING
- recovery executor death at each durable transition
- real package update process death/reboot at each transaction phase
- isolated network interface disappearance and restoration
- full disposable-root rm-style destruction after protected-scope proof
- live bad-postcondition rejection for each recovery provider
- compound runtime corruption plus recovery-executor death
- compound update transaction plus Guardian restart
- Guardian death during live runtime VERIFYING

## Brutally clear V1 boundary

### PREVENT

- authority-replay-and-stale-identity
- protected-filesystem-destruction
- protected-process-signal

### RECOVER AUTOMATICALLY

- bounded-ui-failure-storm
- clipboard-worker-kill
- compound-session-guardian
- compound-session-wallpaper-clipboard
- enospc-durable-publication
- guardian-self-kill
- journal-flood-reconciliation
- quickshell-all-surfaces
- quickshell-surface-kill
- readonly-durable-publication
- session-compositor-kill
- wallpaper-provider-race

### RECOVER WITH AUTHORITY

- immutable-runtime-corruption
- scoped-break-glass
- update-interruption-contracts

### DETECT BUT NOT RECOVER

- corrupt-recovery-prior
- stale-guardian-evidence

### OUTSIDE V1

- update-reboot-interruption

### BUG

- None demonstrated.

This report deliberately makes no claim for a scenario absent from the matrix. A command exit code was never accepted as recovery without the scenario's independent postcondition checks.
