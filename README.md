# MahoOS

MahoOS is an Arch-based desktop operating system built around Hyprland and Quickshell.
It provides its own shell, launcher, connectivity panel, notifications, lock screen,
file manager, power controls, wallpaper system, and recovery tooling.

MahoOS is still in development. The desktop is usable, but V1 installation,
updates, boot recovery, and full system recovery are not finished yet.

## Desktop

The current desktop includes:

- **Maho Edge** — compact system surface and control center
- **Maho Dock** — pinned and running applications
- **Maho Launcher** — applications, files, and commands
- **Maho Link** — Wi-Fi and Bluetooth controls
- **Maho Notify** — notifications, history, and Do Not Disturb
- **Maho Lock** — secure Wayland lock screen and SDDM theme
- **Maho Files** — native Qt/QML file manager using KDE KIO
- **Maho Power** — lock, sleep, log out, restart, and shutdown
- **Maho Clipboard** — clipboard history and pinning
- **Maho Wallpaper** — wallpaper changes and palette generation

## How it works

MahoOS keeps observation, decisions, and system changes separate.

```text
system state
    ↓
observers
    ↓
policy and Guardian
    ↓
certified recovery or system action
    ↓
verification
```

Normal component crashes are left to the service manager when it already owns
recovery. Guardian observes the incident, verifies that recovery worked, records
the result, and only escalates when the normal recovery path cannot restore a
healthy state.

System changes are expected to be bounded, reversible, and verified after they
run. Unknown failures do not receive guessed repair commands.

## Repository layout

```text
apps/        Native applications
bin/         MahoOS commands and runtime entry points
config/      Hyprland, Quickshell, SDDM, and platform configuration
lib/         Shared policy, recovery, security, and application logic
systemd/     User services
packaging/   Arch package files
adapters/    Bounded system adapters
tests/       Contract, regression, and policy tests
docs/        Architecture and component documentation
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Maho Shell](docs/MAHO-SHELL.md)
- [Maho Notify](docs/MAHO-NOTIFY.md)
- [Roadmap](docs/ROADMAP.md)
- [Theme engine](theme/README.md)

## V1 direction

V1 is focused on making the current desktop installable and recoverable as a
complete operating system: packaging, installer, boot generations, Btrfs
recovery, signed updates, Guardian integration, and failure testing.
