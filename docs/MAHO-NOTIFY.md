# Maho Notify

Maho Notify is the MahoOS notification service and notification center.
It runs independently from Maho Edge and owns the desktop notification protocol.

## Popups

- up to three notification cards are visible at once
- extra notifications wait in a bounded in-memory queue
- low, normal, and critical notifications use bounded expiry times
- hovering pauses expiry
- app-provided actions are preserved without inventing new actions
- notification body text is displayed as plain text
- critical notifications remain visible longer and bypass Do Not Disturb
- colors come from the active Maho palette

Maho Notify does not expose inline replies, arbitrary markup, or unbounded
persistent popups.

## History and Do Not Disturb

Notification history is stored as private JSON under:

```text
$XDG_STATE_HOME/maho/notify/state.json
```

with `~/.local/state/maho/notify/state.json` as the fallback path.

History is bounded by age and entry count. Transient notifications are not
persisted. Malformed state is isolated instead of preventing Notify from starting.

Do Not Disturb suppresses low and normal popups while keeping their history.
Critical notifications still appear.

Useful commands:

```text
maho-notify dnd on
maho-notify dnd off
maho-notify dnd toggle
maho-notify dnd status
maho-notify history clear
```

## Notification Center

The notification center is a separate right-side overlay. It provides:

- unread state
- Do Not Disturb control
- grouped history
- relative timestamps
- expandable notification bodies
- keyboard navigation
- clear and read controls

Opening the center marks displayed history as read.
Historical entries do not expose live application actions.

## Maho Edge integration

Notify publishes a small private runtime status file containing only:

- unread count
- Do Not Disturb state
- whether Notify is active
- the live Quickshell process ID

Maho Edge uses this metadata to open the existing notification center and show
unread/DND state. It never reads notification bodies or the persistent history
file.

## Runtime

`maho-notify` supports:

```text
run  start  stop  restart  reload  status  doctor  logs  center
```

The service refuses to take over when another process already owns
`org.freedesktop.Notifications`.

Logs and status output do not include notification content.
