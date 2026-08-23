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
