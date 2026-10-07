# Guardian sensor bake-off result

Date: 2026-10-07

Host used for the accepted live slice:

- x86_64
- kernel `6.18.50-1-cachyos-lts`
- BTF available

The workload created a short process tree, wrote/chmodded/renamed/symlinked/unlinked temporary files, and opened one loopback TCP connection. No external destination was contacted.

## Decision

Use **Tetragon behind a Maho-owned Guardian sensor adapter** for the next Guardian observability prototype.

This is a substrate choice, not an authority choice. Tetragon must remain replaceable and must not own Maho trust, causality, containment, Prevention, recovery, or mutation authority.

Tracee remains a secondary candidate for high-fidelity/on-demand tracing. Falco libs are not accepted as the primary live sensor on the current host because the modern-BPF examples opened successfully but delivered zero events.

## Tetragon

Accepted live run:

`/tmp/maho-guardian-sensor-bakeoff-20261007T154320Z`

Observed:

- 1,726 exported events
- 186 process exec events
- 70 process exit events
- 1,470 kprobe events
- stable `exec_id` and `parent_exec_id`
- exact child -> grandchild process lineage
- process-attributed file write evidence
- process-attributed TCP connect evidence
- zero ring-buffer events lost
- zero ring-buffer queue events lost

Workload-specific evidence included:

- Python process writing the temporary `alpha.txt` with `MAY_WRITE`
- shell child writing the renamed `beta.txt` with `MAY_WRITE`
- Python process opening the expected loopback TCP connection
- exec and exit events retaining the same stable process identity

A startup-time process sample showed about 104 MiB RSS and high CPU while probes were being attached. That is **not** a steady-state measurement and must not be used as an idle-overhead claim.

The first PID-scoped tracing-policy attempt produced only process lifecycle events. A binary-scoped fallback produced the file/network evidence. Production work therefore needs a tighter subject-scoping design before always-on deployment.

## Tracee

Tracee 0.24.1 has a strong event model and earlier exploratory runs demonstrated process identity, filesystem events, network events, and rich syscall coverage.

However, the current-host exact-tree acceptance slice is **not accepted**:

- the first runner attempt used the wrong HTTP server flag spelling
- the corrected attempt reached Tracee but its install path was inside a user-owned evidence directory and Tracee rejected it
- an earlier rich run also exposed a large `parse-arguments-fds` lookup-error storm

The harness now uses a separate temporary Tracee install directory so the next run does not have that path problem. No further privileged rerun was performed in this session to avoid unnecessary authentication prompts.

Do not reject Tracee as incapable. Treat its current evidence as incomplete for the exact-tree gate.

## Falco libs

Falco libs 0.26.0 built successfully from source with the modern eBPF engine using the staged Tetragon `bpftool`.

Both `sinsp-example --modern_bpf` and `scap-open --modern_bpf` opened the engine successfully on the current host, but:

- libsinsp retrieved 0 events
- libscap reported 0 kernel-side events
- libscap reported 0 userspace events

This is a current-host compatibility failure for the bake-off. Do not use Falco libs as Guardian's primary sensor until a later compatibility investigation can make modern-BPF capture produce real events.

Its capture/replay model and explicit drop counters remain useful reference material.

## Guardian integration shape

The next prototype should be:

```text
Tetragon
   |
   v
maho-guardian-sensor-tetragon
   |
   +-- normalize process identity
   +-- normalize file/network observations
   +-- redact/filter sensitive fields
   +-- translate lost-event counters into ObservationGap evidence
   +-- annotate Maho generation/authority context
   |
   v
GuardianEvent ledger
   |
   v
existing Guardian causality / incidents / explanation
```

The adapter should initially consume only the minimum evidence Guardian needs:

- process exec
- process exit
- parent/child identity
- selected file mutation observations
- selected outbound network observations
- provider health and event-loss counters

No Tetragon enforcement actions belong in the first integration.

## Remaining production gate

Before making the sensor always-on, measure a fresh 60-second idle window and a bounded stress workload for:

- steady-state CPU
- steady-state RSS
- event rate
- event loss
- ledger bytes per minute
- startup/teardown reliability
- exact subject filtering
- privacy/redaction behavior
- package footprint

The bake-off selects the prototype substrate. It does not yet certify production always-on overhead.
