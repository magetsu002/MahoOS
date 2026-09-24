# MahoOS

**Linux built to recover.**

MahoOS is an Arch-based desktop operating system for people who want control
without having to babysit the system every time something changes.

On a normal Linux setup, a bad update, broken service, driver problem, or stale
configuration can quickly become your problem to diagnose and undo by hand.
MahoOS is being built around a simpler idea: system changes should be checked,
recoverable, and verified instead of leaving you with a broken machine and a
terminal.

## What MahoOS does differently

You use the computer normally. MahoOS keeps track of important system state in
the background and has known recovery paths for failures it understands.

If something breaks, it does not immediately guess at a repair. It checks what
happened, uses the smallest recovery action it has authority to perform, then
verifies that the system actually returned to a healthy state.

Updates are also being built around an offline candidate system rather than
changing the live system first. Recovery state is prepared before activation so
a failed update does not have to become a broken daily driver.

The goal is simple: **use your computer. Maho takes care of Maho.**

## The desktop

MahoOS has its own desktop surfaces instead of feeling like a collection of
unrelated utilities.

**Maho Edge** is the main system surface for status and quick controls.

**Maho Link** handles Wi-Fi and Bluetooth.

**Maho Notify** handles notifications, history, and Do Not Disturb.

**Maho Launcher** opens apps, files, and commands.

**Maho Files** is the native file manager.

MahoOS also includes its own lock screen, power controls, clipboard history,
dock, wallpaper system, and dynamic colors derived from the active wallpaper.

The point is not just appearance. These parts are designed together so the
system feels consistent and stays out of the way during normal use.

## Recovery and system changes

MahoOS keeps observation, decisions, and system changes separate. A component
that already has a normal restart path is allowed to recover normally. Maho then
checks whether that recovery actually worked.

For larger system changes, Maho uses bounded authority and keeps recovery state
separate from the thing being changed. If the evidence is stale, incomplete, or
unsafe, the system does not pretend everything is healthy.

## Current status

MahoOS is still pre-V1.

The desktop is usable, the recovery system has extensive automated and VM
failure testing, and physical certification of the production kernel update path
is currently in progress.

The installer and ISO are not ready yet. Physical signed-boot certification and
final release hardening are also still unfinished.

## Repository

The main code lives in:

`apps/` for native applications  
`bin/` for Maho commands and runtime entry points  
`config/` for desktop and platform configuration  
`lib/` for recovery, update, policy, and system logic  
`tests/` for regression and contract testing  
`docs/` for architecture and component documentation

More detail is available in the [architecture](docs/ARCHITECTURE.md), [Maho Shell](docs/MAHO-SHELL.md),
[Maho Notify](docs/MAHO-NOTIFY.md), [roadmap](docs/ROADMAP.md), and
[signed boot authority](docs/SIGNED-BOOT-AUTHORITY.md) documentation.
