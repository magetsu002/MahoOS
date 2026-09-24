# Desktop

MahoOS keeps the controls you use every day in a small set of consistent
surfaces.

## Maho Edge

Maho Edge is the compact system surface.

It shows important status and opens the main controls without taking over the
screen. It also handles quick volume, brightness, workspace, and system
feedback.

## Connectivity and notifications

Maho Link is where Wi-Fi and Bluetooth are managed.

Maho Notify handles notification popups, history, unread state, and Do Not
Disturb. Critical notifications can still appear when Do Not Disturb is active.

## Apps and files

Maho Launcher opens applications, files, and commands.

Maho Files is the native file manager.

The dock keeps pinned and running applications together and tries to focus an
existing window instead of creating unnecessary duplicates.

## Lock, power, clipboard, and wallpaper

MahoOS includes its own lock screen, power controls, clipboard history, and
wallpaper controls.

The active wallpaper also drives the desktop palette so the shell can adapt
without every component carrying its own hard-coded colors.

## If something looks wrong

The normal desktop services are managed by systemd and are expected to recover
from ordinary crashes.

For diagnostics, these commands are useful:

`maho-shell status --json`

`maho-shell doctor`

`maho-shell reload`

`maho-notify dnd toggle`
