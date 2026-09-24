# MahoOS

**Linux built to recover.**

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

The desktop is usable. Recovery has extensive automated and VM failure testing,
and the production kernel update path is currently going through physical
certification.

The installer and ISO are not ready yet. Physical signed-boot certification and
final release hardening are also unfinished.

## Learn more

[Architecture](docs/ARCHITECTURE.md)  
[Maho Shell](docs/MAHO-SHELL.md)  
[Maho Notify](docs/MAHO-NOTIFY.md)  
[Roadmap](docs/ROADMAP.md)  
[Signed boot authority](docs/SIGNED-BOOT-AUTHORITY.md)
