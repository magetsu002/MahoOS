# Desktop and platform architecture

This document owns the detailed MahoShell/platform integration contract. The system-wide semantics are canonical in [ARCHITECTURE.md](../ARCHITECTURE.md), and the component routing table is [COMPONENTS.md](../COMPONENTS.md).

## Boundary

MahoShell owns presentation and session UX. It may read MahoSystem status and call bounded controls, but it does not manufacture system truth, trust, or recovery authority.

A desktop surface should answer one of two questions:

1. What does the authoritative backend currently say?
2. Which existing owner should receive this user's requested action?

If a UI needs a new database to mirror a backend that already exists, the design is probably wrong.

## Edge

Maho Edge is the compact top-level system surface. It presents status and routes the user into controls such as audio, brightness, workspaces, Guardian/system status, updates, connectivity, and power.

Edge owns interaction/presentation state only. The underlying state continues to come from the component named in [COMPONENTS.md](../COMPONENTS.md).

## Link

Maho Link is the connectivity surface.

### Wi-Fi

The Wi-Fi adapter reads and controls **NetworkManager** through its existing system interface. Maho may normalize status for UI use, but saved networks, device state, addressing, and connection state remain NetworkManager state.

Maho must not introduce a private Wi-Fi profile database or competing connection manager.

### Bluetooth

The Bluetooth adapter reads BlueZ's ObjectManager state and sends actions to BlueZ D-Bus interfaces. **BlueZ remains authoritative.**

The adapter intentionally does not own a device database. Pairing, connection, trust, device identity, and adapter state must not diverge into Maho-owned copies.

## Files

Maho Files is a native Qt Quick application backed by KDE Frameworks.

- KIO provides listing, metadata, navigation, and file operations.
- KFilePlacesModel/Solid provide places and device setup/eject/teardown behavior.
- Maho Files provides the product UX, search/navigation behavior, and palette integration.

Copy, move, trash, rename, mount/setup, eject, and teardown must stay on those backend contracts rather than becoming a parallel filesystem/device implementation.

## Notify

Maho Notify owns Maho's notification presentation, history, unread state, actions, and Do Not Disturb behavior.

Application identity should resolve through the shared application/XDG model rather than a separate notification-only application registry. Notification UI state must not become MahoSystem health/trust state.

## Launcher and Dock

Launcher and Dock share `lib/maho_app_model.py` for application discovery, identity, icons, and launch/focus behavior.

XDG `.desktop` files remain the application source. The shared model may normalize identities and use current compositor/window state to focus an existing application, but it must not become a replacement application registry.

## Settings direction

A future Maho Settings surface should be a composition layer over existing owners.

Examples:

- networking → NetworkManager;
- Bluetooth → BlueZ;
- audio → PipeWire/WirePlumber;
- application associations → XDG MIME/`mimeapps.list`;
- printing → CUPS;
- secrets → Secret Service;
- Maho reliability controls → the relevant MahoSystem subsystem.

There is no architectural permission to build a universal Maho settings database that shadows those authorities.

## App Resolver direction

The current shared application model already reads XDG desktop entries. A future App Resolver may provide better default-app/association UX, but XDG MIME, `mimeapps.list`, and `.desktop` remain authoritative.

Resolver UX must not create a second default-application database.

## Portals

Maho platform policy selects XDG Desktop Portal providers rather than replacing the portal model.

Current policy delegates chooser/settings-style roles to GTK providers, screen/screenshot/global-shortcut/input-capture roles to the Hyprland provider, and secret portal service to the configured Secret Service provider.

The platform installer owns only Maho-marked policy and bounded provider activation. It must not restart the graphical session, portals, or keyring merely to make configuration look converged.

## Audio

MahoShell binds audio controls to PipeWire state. **PipeWire/WirePlumber remain authoritative** for the graph, default sink, mute, and volume.

Shell state is a presentation cache, not a second mixer authority.

## Secrets and privilege

Secrets use the **Secret Service** contract; current Maho platform wiring activates a standards-based provider rather than storing credentials in a Maho-specific vault.

Privilege authentication uses **PolicyKit** where an interactive administrative decision is needed. Becoming root is not equivalent to receiving a Maho mutation authority.

## Printing

There is no standalone Maho printing product surface in the current source. When one is built, **CUPS** remains the print backend/spooler authority.

## Theme and wallpaper

The Maho theme engine owns Maho's visual palette only.

Wallpaper analysis and palette application are separate. Palette generation is deterministic, validates readable foreground/background relationships, preserves recognizable semantic success/warning/error roles, and keeps a previous working palette for rollback.

The active palette is published at:

```text
~/.cache/maho/theme/active.json
```

Desktop consumers use semantic roles such as background/elevated surfaces, foreground/muted text, accents, borders/focus, and status colors. An optional generator backend may propose colors, but the Maho palette normalization/validation step owns the final visual tokens.

Theme state must never be interpreted as system health, trust, or platform authority.

## Failure rule

A failed presentation surface should be restartable without changing the authority it displays.

If a backend is unavailable, the UI should expose unavailable/unknown state rather than manufacturing a cached success state. Recovery beyond an ordinary surface restart belongs to the relevant system owner, not to the QML view.
