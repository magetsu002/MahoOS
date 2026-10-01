# Component ownership map

Use this document to answer one question:

> **Where does my change belong?**

For the architecture rules behind these boundaries, read [ARCHITECTURE.md](ARCHITECTURE.md). A presentation component may call an authority; it does not become that authority.

| Component / state | Responsibility | Main source location | Canonical backend / authority | Allowed Maho role | Prohibited duplication |
| --- | --- | --- | --- | --- | --- |
| **MahoSystem** | Product system status, diagnostics, reliability/trust presentation | `lib/maho_system_status.py`, `lib/maho_system_cli.py`, `bin/maho` | Underlying subsystem payloads remain authoritative | Aggregate and translate bounded subsystem contracts | A second truth database or universal mutation daemon |
| **Guardian** | Evidence, world state, causality, reliability/security reasoning, verified recovery selection | `lib/guardian_*.py`, Guardian services/CLI | Provider evidence + Guardian's explicit evidence/world-state contracts | Correlate, explain, select accepted recovery, verify | Rewriting provider facts or manufacturing health/trust |
| **Updates** | Candidate discovery/preparation/mutation, admission, activation authority, postboot transaction state | `lib/maho_update_*.py`, `bin/maho-update*` | Maho Update transaction; package manager remains package executor | Own Maho system-update mutation and evidence | A second updater, hidden activation, automatic AUR install |
| **Recovery / generations / GC** | Exact recovery selection, generation identity, retention and safe reclamation | `lib/maho_recovery_*.py`, `lib/guardian_recovery_*.py`, `lib/maho_generation_v2.py`, `lib/maho_generation_gc.py` | Published Maho generation/recovery identities and receipts | Select eligible known-good state and reclaim only proven-unprotected objects | Ad-hoc rollback or age-only deletion |
| **MahoShell / Edge / Dock** | Desktop/session presentation and quick controls | `config/quickshell/maho-shell/`, `bin/maho-shell` | MahoShell presentation; underlying platform/system owners | Present state and request bounded actions | Owning system truth because a control is visible |
| **Networking / Maho Link Wi-Fi** | Wi-Fi discovery, connection controls, network details | `config/quickshell/maho-link/wifi.py` | **NetworkManager** / `nmcli` contract | Thin presentation/control adapter | Private network database, connection manager, or competing network daemon |
| **Bluetooth / Maho Link** | Adapter/device status, pairing and device actions | `config/quickshell/maho-link/bluetooth.py` | **BlueZ D-Bus** | Thin ObjectManager/action adapter | Device database, parallel Bluetooth state, replacement BlueZ control plane |
| **Maho Files** | File browsing, places/devices, file operations | `apps/maho-files/` | **KIO / KFilePlacesModel / Solid** | Native Qt/QML file UI over KDE Frameworks | Parallel filesystem semantics, mount/device database, custom replacement for KIO operations |
| **Audio** | Volume/mute/default sink presentation and control | `config/quickshell/maho-shell/Audio.qml` | **PipeWire / WirePlumber** | Bind shell controls to current audio graph | Parallel mixer state or private audio-device authority |
| **Applications / Launcher / Dock identity** | Application discovery, identity, icons, launch/focus behavior | `lib/maho_app_model.py`, launcher/dock surfaces | **XDG `.desktop` data** and current desktop/window state | Shared Maho app model over XDG entries | Private application registry that diverges from XDG identity |
| **Application associations** | Default handlers / MIME associations | `bin/maho-setup` platform wiring | **XDG MIME, `mimeapps.list`, `.desktop`** | Write/read standards-compliant association state where Maho owns the change | Separate association database |
| **Notifications** | Notification presentation, history, DND and notification-center behavior | `config/quickshell/maho-notify/`, `bin/maho-notify` | Maho notification service + XDG application identity | Own Maho notification UX/history | Separate app identity registry or system-truth store |
| **Theme / wallpaper palette** | Wallpaper-derived semantic desktop palette | `theme/`, wallpaper/theme commands, Maho QML consumers | Maho palette transaction owns only Maho visual tokens | Generate, validate, publish, and roll back Maho palette | Using visual theme state as system authority |
| **Portals** | Desktop portal provider selection/integration | `config/platform/maho-portals.conf`, `lib/maho_platform_install.py` | **XDG Desktop Portal providers** | Install bounded Maho portal policy | Replacement portal protocol or private chooser authority |
| **Secrets** | Secret storage activation/integration | `config/platform/org.freedesktop.secrets.service` and related platform files | **Secret Service** (current provider wiring uses GNOME Keyring) | Configure/activate one standards-based provider | Maho-owned credential vault without an explicit architecture decision |
| **Privilege authentication** | Interactive privilege approval | Policy files and bounded privileged entry points | **PolicyKit** / OS privilege boundary | Request explicit admin authorization for accepted operations | Treating UID 0 as sufficient Maho authority |
| **Printing** | Future printing surface | Not implemented as a Maho product surface yet | **CUPS** | Future UX may present/control CUPS state | A private print spooler or competing print database |
| **Settings** | Future unified settings surface | Not implemented as a standalone Maho Settings owner yet | Existing component/platform authorities | Compose existing owners into one UX | A universal settings database that shadows real owners |
| **App Resolver** | Future default-app/association UX beyond the current shared app model | Direction only; current app model is `lib/maho_app_model.py` | XDG `.desktop` / MIME association contracts | Resolve/present standards-backed choices | Replacing XDG identity/association authority |
| **Prevention** | Protected mutation/process-control enforcement and evidence | `bpf/`, `lib/maho_prevention_*.py`, `lib/maho_mutation_authority.py`, `bin/maho-prevention-boundary` | Exact Maho mutation authority + kernel enforcement boundary | Enforce accepted protected effects | Command-name security, global root ban, unscoped permanent bypass |
| **Installer / boot trust** | Disk plan/assembly, first boot, boot publication, boot/signer/environment identity | `lib/maho_installer_*.py`, `lib/maho_boot_*.py`, `lib/maho_secure_boot.py` | Installer journal + exact disk identity + UEFI/Limine/firmware observations | Assemble existing trust/recovery contracts | A separate installer-only trust model or hidden firmware mutation |

## Routing rule

If a change touches more than one row, name the authoritative row for each state transition in the pull request.

If the required owner does not exist, that is an architecture question, not permission to create one locally. Use the architecture issue template and the contribution-level rules in [CONTRIBUTING.md](../CONTRIBUTING.md).
