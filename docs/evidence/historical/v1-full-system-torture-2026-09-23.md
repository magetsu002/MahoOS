> **HISTORICAL EVIDENCE**
>
> This document records point-in-time certification or design history.
> It is not current project status and does not override current source or canonical architecture documentation.

# MahoOS V1 full-system torture report

- Mission start: `3ec29441bf33c77af47249fc6273cba5f79c504a`
- Certified campaign source: `dea7c54b709b8770ef7ad8d46a50f0d9d17eaae8`
- Ending source before this report commit: `dea7c54b709b8770ef7ad8d46a50f0d9d17eaae8`
- Campaign evidence: `<local path omitted>`
- Verdict: **PASS**
- Distinct scenarios: 35
- Iterations: 66
- Destructive injections: 66

## Source commits

- `dea7c54b709b8770ef7ad8d46a50f0d9d17eaae8` fix(guardian): serialize automatic runtime recovery
- `0bb3754c0c110e6929b9f5e26cde817731728e29` fix(vm): support primary checkout source cleanup
- `a905ac54d6d197a324e74ba8917857be37670d04` update: resume transient package staging failures
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

- detection_latency_ms: samples=24 min=281ms median=336ms p95=5582ms max=5688ms
- recovery_latency_ms: samples=50 min=579ms median=8225ms p95=19775ms max=47734ms
- convergence_latency_ms: samples=50 min=579ms median=8225ms p95=19775ms max=47734ms
- worst outlier: bounded-ui-failure-storm iteration 1 at 47734ms

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
