# Maho Notify

Maho Notify is Maho OS's independent Quickshell notification surface. It owns
desktop notification protocol objects and renders a compact top-right overlay;
it does not render through Maho Edge or reserve compositor layout space.

## N1 behavior

- At most three 324 px cards are visible. Additional notifications wait in a
  memory-only queue until a visible slot opens.
- Body text is rendered as plain text and clamped to three lines. Icons and
  images are bounded to 26 px in the popup.
- Normal notifications default to seven seconds, low urgency to four seconds,
  and critical notifications to fourteen seconds. Application expiry hints are
  honored within bounded ranges: 3–12 seconds normally and 10–20 seconds for
  critical notifications. Zero, negative, and pathological hints use these
  bounded defaults rather than creating a permanent wall.
- Hover pauses the current card timer. The close control calls the protocol
  dismissal path. At most two app-provided actions are shown, and no actions are
  invented.
- Body markup, hyperlinks, body images, action icons, inline reply, and
  persistence are not advertised. Notification content is never logged or
  persisted in N1.
- Colors are read directly from `~/.cache/maho/theme/active.json`, with local
  fallbacks when the active palette is unavailable.

## Runtime

`maho-notify` provides `run`, `start`, `stop`, `restart`, `reload`, `status`,
`doctor`, and bounded `logs` commands. The runtime refuses to start if another
process owns `org.freedesktop.Notifications`; it never stops or disables that
process.

`maho-setup install` packages the command, Quickshell configuration, and user
unit, but intentionally leaves `maho-notify.service` disabled and inactive for
the N1 handoff. Activation remains an explicit user choice after controlled
runtime validation.

## N2 history foundation

History uses stable plain-data snapshots rather than retaining notification
protocol objects. State is stored as atomically replaced JSON below
`$XDG_STATE_HOME/maho/notify/state.json` (falling back to
`~/.local/state/maho/notify/state.json`). The directory is mode `0700` and the
file is mode `0600`. Persistence retains at most 500 non-transient entries and
prunes entries older than seven days. Malformed state is isolated as one private
`.corrupt` file and startup continues with an empty history.

Writes are coalesced, notification content is transferred to the persistence
helper over stdin, and status output exposes counts only. Summaries, bodies,
arbitrary hints, and notification content never enter command arguments or
runtime logs.

Normal notifications from the same application received within six seconds
share one popup slot and show a count; the previous live protocol object is
released after its history snapshot is taken. Critical notifications never use
this grouping path. The popup surface remains capped at three visible groups
plus 100 queued groups, for at most 103 retained popup protocol objects.
When that queue is full, normal/low popup work is released while its history
snapshot remains. A new critical notification replaces the oldest queued
lower-urgency popup, or the oldest queued critical popup when every queued item
is critical, so the newest critical state remains visible without breaking the
hard live-object bound.

DND is persisted with history. Low and normal notifications are archived but
their popup work is immediately released while DND is on. Critical
notifications explicitly bypass DND. `maho-notify dnd on|off|toggle|status` and
`maho-notify history clear` manage this state without printing notification
content; `status --json` exposes counts, DND, and bounded popup metadata only.

The N2 Notification Center is an independent 420 px right-side overlay with a
height capped at 680 px and the current monitor's safe area. It uses a
virtualized, reusable `ListView`, dense grouped history rows, two-line collapsed
bodies, eight-line expanded bodies, DND/read/clear controls, and Escape to
close. Opening the center marks displayed history read. Historical snapshots do
not expose live app-action buttons. `maho-notify center` opens the surface.
