# Maho Launcher L1

Maho Launcher is a native Wayland application launcher built with Quickshell.
It is deliberately independent from Maho Edge and Maho Notify, and it does not
reserve compositor space or replace the current global Rofi launcher binding.

## Run it manually

After `maho-setup install`:

```bash
maho-launcher open
```

From a development checkout without installing:

```bash
MAHO_LAUNCHER_CONFIG_DIR="$PWD/config/quickshell/maho-launcher" \
  bash bin/maho-launcher open
```

Use `maho-launcher toggle`, `maho-launcher close`, `maho-launcher status`,
`maho-launcher doctor`, or `maho-launcher logs 120` for bounded runtime control.

## Apps mode

The launcher reads `DesktopEntries.applications`, Quickshell's freedesktop
desktop-entry index. That model already excludes entries marked `Hidden` or
`NoDisplay`. Search ranks exact, prefix, substring, metadata, and fuzzy
subsequence matches across app name, generic name, comment, keywords, and
categories.

Launching uses `DesktopEntry.execute()`. Maho Launcher never shell-evaluates a
desktop entry's raw `Exec` field. The launcher closes just after handing the
selected entry to Quickshell.

Keyboard controls:

- `Up` / `Down` select a result.
- `Enter` launches the selected app.
- `Escape` closes the launcher.

Rows also support mouse hover and click. The results viewport is clipped and
scroll-bounded. Files and Commands are present as polished L1 empty states;
arbitrary command execution is intentionally unavailable.

## Adaptive palette

`LauncherTheme.qml` watches:

```text
~/.cache/maho/theme/active.json
```

Panel tint, borders, search, tabs, selected rows, logo, focus rings, footer
chips, text relationships, and mascot glow derive from that live palette. Safe
fallback colors keep the launcher usable if the file is missing or invalid.
Application icons are never recolored.

## Mascot and logo assets

The mascot is a separate, pointer-passive layer outside `MaterialPanel`. Its
artwork is replaceable at `assets/maho-mascot.png` and can later be hidden or
animated without changing launcher layout. The header mark is a separate
monochrome asset whose displayed color comes from the adaptive primary token.
The standard search, tab, and fallback glyphs are rasterized from the system's
Adwaita icon library (LGPL-3.0-or-later / CC-BY-SA-3.0) rather than redrawn.

## Privacy and process safety

The runtime uses a non-blocking `flock` plus exact Quickshell argument matching
to prevent duplicates. It never records query text or desktop-entry launch
arguments. `close` and `toggle` signal only a Quickshell process whose argument
identifies the Maho Launcher configuration.

## L2

- Real bounded file search with explicit privacy boundaries.
- A safe curated command/action registry (never arbitrary shell eval).
- Usage-aware ranking and optional number shortcuts.
- Mascot enable/disable and animation preferences.
- User-approved replacement of the existing global launcher binding.
