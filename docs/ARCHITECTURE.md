# Architecture

MahoOS separates system observation, decisions, and mutation so that a failure in
one layer cannot silently gain authority over another.

## Main layers

### Desktop

Quickshell and native Qt/QML components provide the visible desktop:
Maho Edge, Dock, Launcher, Link, Notify, Lock, Clipboard, Power, and Files.

Desktop components read shared system state and palette data. They do not own
arbitrary system repair.

### State

Observers collect system facts without changing the machine.

Examples include service state, security findings, connectivity state, session
state, and the active wallpaper palette.

### Policy

Policy converts normalized state into a decision.

Policy may recommend an action, require confirmation, or refuse to act. It does
not perform the action itself.

### Adapters and recovery providers

Mutating work is performed only by a known adapter or recovery provider.
Examples include systemd service recovery, Maho runtime rollback, system-state
recovery, and boot recovery.

Every supported mutation should have:

1. a defined owner
2. a bounded action
3. a precondition
4. a postcondition
5. a rollback or handoff path when appropriate

### Native admission

System candidates cross a candidate-first admission boundary before they can
receive promotion authority. Maho inspects an isolated candidate against its
exact base and builds a content- and metadata-bound mutation graph covering
files, services, persistence, privilege boundaries, package hooks, boot state,
kernel modules, package ownership collisions, and isolated listener evidence.

The result is `ALLOW`, `REVIEW`, or `REJECT`. Only `ALLOW` can produce an exact
transaction-, candidate-, and graph-bound promotion authority, and the
candidate is inspected again when that authority is consumed. Incomplete,
unisolated, ambiguous, or drifted evidence fails closed.

### Guardian

Guardian coordinates failures across these layers.

It owns incident identity, severity, recovery policy, verification, history, and
escalation. It does not replace a recovery mechanism that already has a clear
owner.

For example, if a Maho user service crashes and systemd is configured to restart
it, systemd performs the restart. Guardian observes the failure, correlates the
replacement process, verifies that it remains healthy, and records the result.

## Runtime layout

`maho-setup` builds immutable runtime releases and switches the active release
through a managed pointer. The previous verified runtime is kept for recovery.

Mutations must be verifiable and reversible.

User services are managed by systemd. Hyprland session startup and shutdown are
owned by Maho session tooling rather than ad-hoc autostart commands.

## Guardian delegated service recovery

Guardian observes short-lived systemd user-service failures from structured
journal manager events. A durable journal cursor prevents a 300-second
reconciliation interval from missing a roughly two-second restart, while exact
manager message IDs, unit names, boot IDs, and invocation IDs prevent ordinary
application logs from creating incidents.

`maho-notify.service` has one exact product-owned contract: systemd-user owns
`Restart=on-failure`; Guardian owns incident identity, correlation, severity,
stability verification, history, and escalation. Guardian does not issue a
competing restart. Recovery is successful only when a different invocation is
still `active/running` after the bounded verification interval.
If systemd does not produce that replacement within the bounded provider
window, the incident remains visible and becomes diagnosis-only; Guardian does
not bypass start limits with another restart.

## Guardian Recovery interface

Guardian Recovery has a dependency-light terminal interface for recovery and
initramfs environments. It displays the lost-trust evidence, exact selected
SystemGeneration and KernelGeneration, smallest authorized recovery scope,
execution progress, and verified result from Guardian-owned JSON documents.

The interface cannot create repair steps or execute them. User confirmation
produces only a plan-bound authorization request; Guardian and the certified
recovery provider retain authority and must independently validate that request.
Invalid, incomplete, or cross-bound evidence produces a safe refusal.

## Theme data

Wallpaper changes produce one canonical palette. Desktop components consume
semantic roles from that palette instead of hard-coded wallpaper colors.

The active palette is stored at:

```text
~/.cache/maho/theme/active.json
```

## Safety rules

- observation does not mutate
- policy does not mutate
- runtime data cannot grant itself recovery authority
- unknown targets do not inherit permissions by name or prefix
- successful recovery requires a verified postcondition
- repeated failure is evidence, not an automatic severity rule
- catastrophic incidents are never repaired through guessed autonomous actions
