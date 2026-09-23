# MahoOS V1 full-system torture report

- Mission start: `8ce0f3eb2791e052f764b8633a41d3946acf97ca`
- Certified campaign source: `649bff02262ebd68899972617e152d8b2a057a3b`
- Ending source before this report commit: `649bff02262ebd68899972617e152d8b2a057a3b`
- Campaign evidence: `/home/magetsu/.local/state/maho/certification/vm-torture/20260923T122456Z-649bff02262ebd68899972617e152d8b2a057a3b`
- Verdict: **PASS**
- Distinct scenarios: 35
- Iterations: 66
- Destructive injections: 66

## Source commits

- `649bff02262ebd68899972617e152d8b2a057a3b` Document final torture harness fixes
- `267180578543fe928ce2a264368f783b6614ffe5` Merge remote-tracking branch 'origin/main' into feat/full-system-torture-vm
- `29d76db7ab487d075189e00d0dd87e6a45ec490f` Assert real update recovery result correctly
- `933606883e3faec9b7e911965e67dfc5af0d5322` Fix durable update torture journals
- `63c41899ff6b46cdb99c1e24d7ce2114fd142e2b` Merge remote-tracking branch 'origin/main' into feat/full-system-torture-vm
- `5d311d43a937f8a0839884509338138855a8b474` Complete update interruption torture coverage
- `fefb647950f1a0637293142460bf7cce8eea00e0` test(vm): add full disposable root destruction
- `51fe12a2a262cc4721b64b0a97d78cbf4b3e1169` test(vm): isolate Guardian verifying fault cut point
- `502378f3d9054c283cc978b01b3670d0bb5c482e` test(vm): make recovery power-cycle assertions phase-aware
- `4c37846add2be6df59a2ad6ac2f8a75589b3b0d4` test(vm): use valid transaction identity in update compound case
- `a4d62afdace104772aa020a0119665136c3b0a7d` test(vm): add persistent recovery power-cycle coverage
- `4c89c1c71f245dd5a1dca1a3561668ee72484b08` test(vm): recognize verifying as durable post-mutation state
- `de25e188dc842dbcdcf23f56099e83a05ac118ae` test(vm): preserve torture result after executor fault
- `a466d346cf64c1c2b24136ee1b44131672a144e7` test(vm): isolate runtime interruption phases
- `195925d08bf508bd5df83750a9335af3f73e657c` test(vm): establish Guardian stream continuity before recovery faults
- `17466332b7db2cc43caaaf921ccedae7e61a7c80` test(vm): extend live torture coverage
- `0c8ecff86e64dcbc1d1984088ee6afd4fae5291f` docs(vm): publish V1 full-system torture evidence
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

- PREVENTED: 4
- RECOVERED_AUTOMATICALLY: 53
- RECOVERED_WITH_AUTHORITY: 3
- DETECTED_ONLY: 6
- NOT_COVERED: 0
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
| isolated-network-loss | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| bad-postcondition-runtime | 1 | DETECTED_ONLY | DETECTED_ONLY | True |
| bad-postcondition-session | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| bad-postcondition-wallpaper | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| recovery-loop-prevention | 1 | DETECTED_ONLY | DETECTED_ONLY | True |
| authority-replay-and-stale-identity | 1 | PREVENTED | PREVENTED | True |
| protected-filesystem-destruction | 1 | PREVENTED | PREVENTED | True |
| protected-process-signal | 1 | PREVENTED | PREVENTED | True |
| scoped-break-glass | 1 | RECOVERED_WITH_AUTHORITY | RECOVERED_WITH_AUTHORITY | True |
| runtime-reboot-awaiting | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| runtime-reboot-recovering | 1 | DETECTED_ONLY | DETECTED_ONLY | True |
| update-phase-reboot-durability | 1 | DETECTED_ONLY | DETECTED_ONLY | True |
| runtime-reboot-verifying | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| full-disposable-root-destruction | 1 | PREVENTED | PREVENTED | True |
| corrupt-recovery-prior | 1 | DETECTED_ONLY | DETECTED_ONLY | True |
| immutable-runtime-corruption | 1 | RECOVERED_WITH_AUTHORITY | RECOVERED_WITH_AUTHORITY | True |
| recovery-executor-death-before-mutation | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| recovery-executor-death-after-mutation | 2 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| guardian-death-during-runtime-verifying | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
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
| real-package-mutation-interruption | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |
| update-interruption-contracts | 1 | RECOVERED_WITH_AUTHORITY | RECOVERED_WITH_AUTHORITY | True |
| compound-update-guardian-restart | 1 | RECOVERED_AUTOMATICALLY | RECOVERED_AUTOMATICALLY | True |

## Host safety

- boot_id_unchanged: True
- root_source_unchanged: True
- source_revision_unchanged: True
- source_clean_after_campaign: True
- prevention_state_unchanged: True
- maho_services_unchanged: True

## Bugs found

- No Maho V1 product bug was demonstrated by the completed scenarios.
- Six torture-harness defects were found and fixed without weakening product assertions: read-only media classification, pre-staging script loading, fresh-user Guardian startup, wallpaper provider/JSON readiness, immutable update-journal binding, and explicit propagation of real package-interruption assertion failures.

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
- A real pacman package mutation was killed after the target appeared; recovery removed partial package state and did not promote a generation.
- Durable PREPARED through ACTIVE_VERIFYING update states survived a same-disk power cycle with a changed guest boot ID and no false HEALTHY state.

## Prevention and storage

- Protected mutations and signals were denied across direct, Python, opaque binary, alias, and namespace paths.
- Expired/wrong-identity authorities were denied; exact short-lived authorities worked and were evidenced.
- ENOSPC/read-only publication preserved valid durable JSON and resumed after the fault cleared.

## Compound failures

- 5/5 simultaneous Guardian plus compositor failures converged.
- Simultaneous compositor, wallpaper-provider, and clipboard-owner failure converged.
- Eight rapid Notify failures remained bounded and closed without runaway incident growth.

## Performance

- detection_latency_ms: samples=24 min=281ms median=325ms p95=5629ms max=5878ms
- recovery_latency_ms: samples=50 min=581ms median=7926ms p95=18409ms max=46633ms
- convergence_latency_ms: samples=50 min=581ms median=7926ms p95=18409ms max=46633ms
- worst outlier: bounded-ui-failure-storm iteration 1 at 46633ms

## Required coverage not yet demonstrated

- None. Every required V1 torture cell met its evidence-backed minimum.

## Brutally clear V1 boundary

### PREVENT

- authority-replay-and-stale-identity
- full-disposable-root-destruction
- protected-filesystem-destruction
- protected-process-signal

### RECOVER AUTOMATICALLY

- bad-postcondition-session
- bad-postcondition-wallpaper
- bounded-ui-failure-storm
- clipboard-worker-kill
- compound-session-guardian
- compound-session-wallpaper-clipboard
- compound-update-guardian-restart
- enospc-durable-publication
- guardian-death-during-runtime-verifying
- guardian-self-kill
- isolated-network-loss
- journal-flood-reconciliation
- quickshell-all-surfaces
- quickshell-surface-kill
- readonly-durable-publication
- real-package-mutation-interruption
- recovery-executor-death-after-mutation
- recovery-executor-death-before-mutation
- runtime-reboot-awaiting
- runtime-reboot-verifying
- session-compositor-kill
- wallpaper-provider-race

### RECOVER WITH AUTHORITY

- immutable-runtime-corruption
- scoped-break-glass
- update-interruption-contracts

### DETECT BUT NOT RECOVER

- bad-postcondition-runtime
- corrupt-recovery-prior
- recovery-loop-prevention
- runtime-reboot-recovering
- stale-guardian-evidence
- update-phase-reboot-durability

### OUTSIDE V1

- None demonstrated.

### BUG

- None demonstrated.

This report deliberately makes no claim for a scenario absent from the matrix. A command exit code was never accepted as recovery without the scenario's independent postcondition checks.
