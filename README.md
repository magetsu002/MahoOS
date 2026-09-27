# MahoOS

**Linux that takes responsibility for itself without taking control away from you.**

MahoOS is an Arch-based desktop for people who want the control of Linux without
having to babysit it every time something changes.

A bad update, broken service, driver problem, or bad configuration can turn into
hours of manual repair. MahoOS is being built so the system can check important
changes, keep a recovery path, and verify that recovery actually worked.

## Why MahoOS exists

The goal is to make daily use simple.

You should be able to update the system, connect your devices, change your
desktop, and get on with what you were doing without maintaining a pile of
separate scripts and tools.

When Maho knows how to recover from a problem, it can do that and check the
result. When it does not have enough information to act safely, it stops instead
of guessing.

Updates are being built around a separate candidate system so a failed update
does not have to damage the system you are currently using.

**Use your computer. Maho takes care of Maho.**

## The desktop

MahoOS has its own shell and system controls, designed to feel like one product.

**Maho Edge** gives you quick system controls and status.

**Maho Link** handles Wi-Fi and Bluetooth.

**Maho Notify** handles notifications and Do Not Disturb.

**Maho Launcher** opens apps, files, and commands.

**Maho Files** is the native file manager.

MahoOS also includes its own lock screen, dock, power controls, clipboard
history, and wallpaper system. The desktop colors adapt to the active wallpaper
so the whole system stays visually consistent without manual tweaking.

## Current status

MahoOS is still pre-V1.

The historical pre-installer gate is complete. The `v1-preinstaller-rc0` tag
points to `2d138aa930031f63b4c15a9234a11ce69a26f5e3`, and current main is
`4fedab78d31109025855eb30f425f677f97b6b7d`.

The desktop is usable, recovery has extensive automated and VM failure testing,
and the production kernel update path has transaction-backed physical
certification. Immutable runtime deployment, persistence baseline transition
authority, and the boot-bound firewall receipt path are no longer pre-installer
blockers.

Current V1 work is the installer and certified first boot, automatic
maintenance/update coordination, bad-update recovery closure, production
Prevention VM certification after the installer VM exists, fresh-install
reproducibility, and the physical Signed Boot/hardware release gates.

## Learn more

[Desktop](docs/DESKTOP.md)

[Recovery](docs/RECOVERY.md)

[Architecture](docs/ARCHITECTURE.md)

[Roadmap](docs/ROADMAP.md)
