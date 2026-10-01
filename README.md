<p align="center">
  <img src="docs/assets/brand/mahoos-banner.png" alt="MahoOS" width="100%" height="240">
</p>

# MahoOS

**Linux built to recover.**

MahoOS is a Pre-V1 Arch-based operating system and desktop platform built around one rule: important changes should be **owned, reversible, and verified**.

> **Own the system. Trust the system. Stop babysitting the system.**

**Pre-V1:** active development. Interfaces and guarantees may still change before V1.

## Preview

<details open>
<summary><strong>Maho Lock / SDDM</strong></summary>
<br>
<p align="center">
  <a href="docs/assets/preview/maho-lock.png">
    <img src="docs/assets/preview/maho-lock.png" alt="Maho Lock and SDDM screen" width="100%">
  </a>
</p>
</details>

<details>
<summary><strong>Desktop &amp; Dock</strong> — window previews, dock, and desktop composition</summary>
<br>
<p align="center">
  <a href="docs/assets/preview/maho-dock.png">
    <img src="docs/assets/preview/maho-dock.png" alt="MahoOS desktop, window preview, and dock" width="100%">
  </a>
</p>
</details>

<details>
<summary><strong>Maho Edge</strong> — system controls, health, media, and entry points</summary>
<br>
<p align="center">
  <a href="docs/assets/preview/maho-edge.png">
    <img src="docs/assets/preview/maho-edge.png" alt="Maho Edge quick controls" width="58%">
  </a>
</p>
</details>

<details>
<summary><strong>Maho Launcher</strong> — apps, files, commands, and quick actions</summary>
<br>
<p align="center">
  <a href="docs/assets/preview/maho-launcher.png">
    <img src="docs/assets/preview/maho-launcher.png" alt="Maho Launcher" width="82%">
  </a>
</p>
</details>

<details>
<summary><strong>Maho Link</strong> — Wi-Fi and Bluetooth connectivity</summary>
<br>
<p align="center">
  <strong>Wi-Fi</strong><br><br>
  <a href="docs/assets/preview/maho-link-wifi.png">
    <img src="docs/assets/preview/maho-link-wifi.png" alt="Maho Link Wi-Fi view" width="54%">
  </a>
</p>

<p align="center">
  <strong>Bluetooth</strong><br><br>
  <a href="docs/assets/preview/maho-link-bluetooth.png">
    <img src="docs/assets/preview/maho-link-bluetooth.png" alt="Maho Link Bluetooth view" width="54%">
  </a>
</p>

<p align="center"><sub>NetworkManager owns networking state. BlueZ owns Bluetooth state.</sub></p>
</details>

<details>
<summary><strong>Maho Files</strong> — native Qt/KIO file management</summary>
<br>
<p align="center">
  <a href="docs/assets/preview/maho-files.png">
    <img src="docs/assets/preview/maho-files.png" alt="Maho Files" width="100%">
  </a>
</p>
<p align="center"><sub>Places, devices, search, context actions, and filesystem operations.</sub></p>
</details>

<details>
<summary><strong>Maho Notify</strong> — held delivery, Adaptive Focus, and notification history</summary>
<br>
<p align="center">
  <a href="docs/assets/preview/maho-notify.png">
    <img src="docs/assets/preview/maho-notify.png" alt="Maho Notify notification center" width="58%">
  </a>
</p>
</details>

<details>
<summary><strong>Power &amp; Session</strong> — explicit session and power actions</summary>
<br>
<p align="center">
  <a href="docs/assets/preview/maho-power.png">
    <img src="docs/assets/preview/maho-power.png" alt="Maho Power and Session dialog" width="100%">
  </a>
</p>
</details>

<details>
<summary><strong>Wallpaper Picker &amp; Dynamic Palette</strong> — wallpaper selection and palette adaptation</summary>
<br>
<p align="center">
  <a href="docs/assets/preview/maho-wallpaper.png">
    <img src="docs/assets/preview/maho-wallpaper.png" alt="Maho wallpaper picker and dynamic palette controls" width="100%">
  </a>
</p>
<p align="center"><sub>Wallpaper-driven palettes keep the shell visually coherent with the active desktop.</sub></p>
</details>

## Why MahoOS

- **Recover deliberately.** Risky system changes are tied to known-good recovery state and verified afterward.
- **Trust current evidence.** Missing or stale evidence never silently becomes healthy or trusted state.
- **Bound authority.** Privilege alone is not enough; mutation authority is explicit, scoped, and attributable.
- **Stay native.** MahoOS coordinates Linux authorities such as NetworkManager, BlueZ, KIO/Solid, PipeWire/WirePlumber, and XDG instead of replacing them with parallel state.

MahoOS is not a theme pack or an Arch rice. The desktop and reliability system are built as one product.

## Architecture in one minute

- **MahoShell** — the visible desktop, controls, and presentation.
- **MahoSystem** — Guardian truth, trust, updates, generations, recovery, and bounded system authority.
- **Linux authorities** — the existing subsystem owners that remain authoritative for networking, Bluetooth, files, audio, application identity, and related state.

MahoShell presents and requests. MahoSystem decides and coordinates.

Read the full model in [Architecture](docs/ARCHITECTURE.md) or use [Components](docs/COMPONENTS.md) to find where a change belongs.

<details>
<summary><strong>Reliability contract</strong></summary>
<br>

- unknown, stale, or missing evidence is not healthy evidence;
- operational health is not the same thing as trust;
- root privilege is not sufficient mutation authority;
- authority is exact, bounded, scoped, expiring, and attributable;
- Maho Update owns system-update mutation and automatic AUR installation is forbidden;
- reboot, shutdown, firmware mutation, and destructive user-disk actions are never hidden.

</details>

## Project status

MahoOS is **Pre-V1**, not a general-release claim. The repository already contains substantial desktop, Guardian, generation, update/recovery, prevention, installer, first-boot, and boot-trust work. Fresh-install convergence, broader certification, physical trust/provisioning gates, and release governance are still being completed.

See the [Roadmap](docs/ROADMAP.md). Historical certification remains under `docs/history/` and `docs/evidence/` as evidence, not current authority.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — canonical system model
- [Components](docs/COMPONENTS.md) — ownership and routing map
- [Development](docs/DEVELOPMENT.md) — build, test, package, diagnose
- [Contributing](CONTRIBUTING.md) — contribution rules
- [Roadmap](docs/ROADMAP.md) — Pre-V1 → V1 direction
- [Security](SECURITY.md) — disclosure and reporting policy
- [AGENTS.md](AGENTS.md) — machine and AI contributor contract

## License

Unless otherwise stated, original MahoOS code is licensed under **GPL-3.0-only**. Files and third-party material carrying their own license notices remain governed by those terms. See [LICENSE](LICENSE) and [Third-party notices](THIRD_PARTY_NOTICES.md).
