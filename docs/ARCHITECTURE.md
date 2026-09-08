# Maho OS Architecture

## Layers

### Core

Stable user behavior and system contracts.

Examples:

- input behavior
- keybindings
- window semantics
- workspaces
- monitor fundamentals

This layer should rarely adapt automatically.

### Appearance

Replaceable visual behavior.

Examples:

- decorations
- animation
- effects
- shell presentation

### Theme

Canonical visual palette and theme consumers.

The long-term model is:

wallpaper/input
→ palette generator
→ canonical Maho palette
→ desktop consumers

### State

Observes the system without mutating it.

### Policy

Consumes normalized state and decides desired state.

Policy does not mutate the operating system.

### Adapters

The only layer allowed to perform adaptive mutations.

Every meaningful mutation should be:

1. planned
2. applied
3. verified
4. recorded
5. reversible

### Recovery

Restores known-good state when an adaptation or configuration fails.

## Fundamental rule

Observation cannot mutate.

Policy cannot mutate.

Only adapters mutate.

Mutations must be verifiable and reversible.

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
