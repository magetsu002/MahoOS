# MahoOS

**MahoOS — Linux built to recover.**

MahoOS is a Pre-V1 Arch-based operating system and desktop platform for people who want Linux control without having to babysit the machine after every update, service failure, driver change, or configuration mistake.

Its core promise is simple:

> **Own the system. Trust the system. Stop babysitting the system.**

MahoOS is not a theme pack or an Arch rice. It combines a native desktop with a reliability layer designed around explicit authority, current evidence, reversible change, and verified recovery.

## What problem it solves

Traditional Linux desktops give you powerful tools, but they often leave the user to connect the pieces when something breaks. MahoOS is being built so important changes have an identified owner, recovery state exists before risky mutation, and success is verified instead of assumed.

The system prefers the smallest known-good recovery path. If it does not have enough current evidence to act safely, it stops rather than guessing.

## The shape of MahoOS

```text
                         MahoOS
                ┌────────────────────┐
                │     MahoShell      │
                │ desktop + controls │
                └─────────┬──────────┘
                          │ presents / requests
                ┌─────────▼──────────┐
                │     MahoSystem     │
                │ truth + reliability│
                └─────────┬──────────┘
                          │ consumes
        ┌─────────────────┼─────────────────┐
        │                 │                 │
   observers         mutation owners   Linux authorities
   evidence          exact effects     NM / BlueZ / KIO /
   Guardian          Update / Recovery PipeWire / XDG / …
```

**MahoShell** owns the visible desktop experience. **MahoSystem** is the system/reliability domain that presents bounded status and coordinates existing subsystem contracts; it is not a second Linux underneath Linux.

The canonical model is in [Architecture](docs/ARCHITECTURE.md).

## Desktop

The desktop is built around Hyprland, Quickshell, Qt/QML, and native integrations.

Current broad surfaces include Maho Edge, Link, Notify, Launcher, Files, Dock, Lock, Power, Clipboard, wallpaper/theme integration, Guardian status, and system/update controls.

Maho surfaces reuse the platform authorities that already own the real state. NetworkManager still owns networking. BlueZ still owns Bluetooth. KIO and Solid still own file/device operations. PipeWire/WirePlumber still own audio. XDG desktop and MIME data still own application identity and associations.

See [Components](docs/COMPONENTS.md) for the routing map.

## Preview

Public preview images below reflect current MahoOS desktop surfaces. Personal network/device identifiers and notification contents are replaced with demo-safe values. Every image links to its full-resolution file.

### Desktop and Dock

<p align="center">
  <a href="docs/assets/preview/maho-dock.png">
    <img src="docs/assets/preview/maho-dock.png" alt="MahoOS desktop, window preview, and dock" width="100%">
  </a>
</p>

### Maho Lock

<p align="center">
  <a href="docs/assets/preview/maho-lock.png">
    <img src="docs/assets/preview/maho-lock.png" alt="Maho Lock screen" width="100%">
  </a>
</p>

### Edge and Launcher

<table>
<tr>
<td width="50%" align="center" valign="top">
  <a href="docs/assets/preview/maho-edge.png">
    <img src="docs/assets/preview/maho-edge.png" alt="Maho Edge quick controls" width="100%">
  </a>
  <br><strong>Maho Edge</strong><br>
  <sub>System controls, health, media, and entry points.</sub>
</td>
<td width="50%" align="center" valign="top">
  <a href="docs/assets/preview/maho-launcher.png">
    <img src="docs/assets/preview/maho-launcher.png" alt="Maho Launcher" width="100%">
  </a>
  <br><strong>Maho Launcher</strong><br>
  <sub>Apps, files, commands, and quick actions.</sub>
</td>
</tr>
</table>

### Maho Link

<table>
<tr>
<td width="50%" align="center" valign="top">
  <a href="docs/assets/preview/maho-link-wifi.png">
    <img src="docs/assets/preview/maho-link-wifi.png" alt="Maho Link Wi-Fi view" width="100%">
  </a>
  <br><strong>Wi-Fi</strong>
</td>
<td width="50%" align="center" valign="top">
  <a href="docs/assets/preview/maho-link-bluetooth.png">
    <img src="docs/assets/preview/maho-link-bluetooth.png" alt="Maho Link Bluetooth view" width="100%">
  </a>
  <br><strong>Bluetooth</strong>
</td>
</tr>
</table>

Maho Link presents connectivity through the system authorities that own the real state: NetworkManager for networking and BlueZ for Bluetooth.

### Maho Files

<p align="center">
  <a href="docs/assets/preview/maho-files.png">
    <img src="docs/assets/preview/maho-files.png" alt="Maho Files" width="100%">
  </a>
</p>

Native Qt/KIO file management with places, devices, search, and filesystem operations.

### Notify and Power

<table>
<tr>
<td width="50%" align="center" valign="top">
  <a href="docs/assets/preview/maho-notify.png">
    <img src="docs/assets/preview/maho-notify.png" alt="Maho Notify notification center" width="100%">
  </a>
  <br><strong>Maho Notify</strong><br>
  <sub>Held delivery, Adaptive Focus, and notification history.</sub>
</td>
<td width="50%" align="center" valign="top">
  <a href="docs/assets/preview/maho-power.png">
    <img src="docs/assets/preview/maho-power.png" alt="Maho Power and Session dialog" width="100%">
  </a>
  <br><strong>Power &amp; Session</strong><br>
  <sub>Explicit session and power actions.</sub>
</td>
</tr>
</table>

### Dynamic wallpaper palette

<p align="center">
  <a href="docs/assets/preview/maho-wallpaper.png">
    <img src="docs/assets/preview/maho-wallpaper.png" alt="Maho wallpaper and dynamic palette picker" width="100%">
  </a>
</p>

Wallpaper-driven dynamic palettes keep the shell visually coherent with the active desktop.

## Reliability philosophy

MahoOS is fail-safe by default:

- unknown, stale, or missing evidence is not healthy evidence;
- operational health is not the same thing as trust;
- root privilege is not sufficient mutation authority;
- observers observe and mutation owners mutate;
- authority is exact, bounded, scoped, expiring, and attributable;
- historical proof never establishes current trust;
- Maho Update owns system-update mutation;
- automatic AUR installation is forbidden;
- reboot, shutdown, firmware mutation, and destructive user-disk actions must never be hidden.

The full semantics live in [Architecture](docs/ARCHITECTURE.md).

## Pre-V1

MahoOS is still **Pre-V1**. The repository already contains substantial desktop, Guardian, generation, update/recovery, prevention, installer, first-boot, and boot-trust work, but Pre-V1 is not a claim of general release readiness.

Broad unfinished work includes fresh-install and release convergence, bounded hardware certification, physical trust/provisioning gates, broader failure certification, and final public-release governance. Interfaces and guarantees may still change before V1.

Historical certification is retained under `docs/history/` and `docs/evidence/`, but it is not part of the normal contributor reading path and does not override current source.

## Start here

1. [Architecture](docs/ARCHITECTURE.md) — the canonical mental model.
2. [Components](docs/COMPONENTS.md) — where a change belongs.
3. [Contributing](CONTRIBUTING.md) — how to change MahoOS safely.
4. [Development](docs/DEVELOPMENT.md) — build, test, package, and diagnose.
5. [Roadmap](docs/ROADMAP.md) — broad Pre-V1 → V1 direction.
6. [Security](SECURITY.md) — security reporting and disclosure policy.

Machine and AI contributors should also read [AGENTS.md](AGENTS.md).
