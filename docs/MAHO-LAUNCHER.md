# Maho Launcher

Maho Launcher is Maho's production application launcher. Rofi is the mature
underlying engine; Maho owns the product command, safe mode integration,
Palette V2 translation, visual theme, compositor material rule, and Maho Edge
bridge. Maho does not claim authorship of Rofi.

## Architecture

The production command is `maho-launcher`. `open` launches native Rofi `drun`,
so desktop-entry discovery, fuzzy matching, icon resolution, keyboard and mouse
navigation, launch semantics, and history remain Rofi responsibilities.

The visible modes are:

- **Apps** — Rofi `drun`, using real installed desktop entries and icons.
- **Files** — Rofi's built-in `filebrowser`; it does not index the home folder
  with a custom per-keystroke scanner.
- **Commands** — a short exact allowlist. Current entries regenerate launcher
  colors, open launcher diagnostics, open Kitty, open Thunar, or lock with
  Hyprlock when those commands exist. Search text is never evaluated.

The former custom Quickshell implementation remains historical/experimental on
`feat/maho-launcher`. Production does not import it or invoke Quickshell.

## Reference A implementation

`config/rofi/maho-launcher/launcher.rasi` recreates the frozen approved
Reference A as closely as Rofi 2.0 permits: a centered 720×720 logical glass
panel, 24px outer radius, calm centered title, inset search, a single segmented
mode surface, eight generous rows, one shared result container, a softly edged
selection slab, native app icons, secondary desktop metadata when available,
and quiet activation chevrons. It intentionally has no mascot, decorative
branding, shortcut-number badges, or keyboard tutorial footer.

The header and footer affordances use supported Rofi actions:

- The app-grid control clears the Apps query, returning to the full `drun`
  list. In another mode it clears that mode's query.
- From the initial Apps mode, the settings control wraps to Commands, the
  bounded launcher action menu. Rofi does not expose a theme-button action that
  targets an arbitrary named mode; in other modes the control performs standard
  previous-mode navigation and Commands remains directly clickable.
- “Show more apps” performs Rofi's real next-page action. The list remains
  scrollable and no second result engine is introduced.

## Palette V2

`lib/maho_launcher_theme.py` reads the canonical
`~/.cache/maho/theme/active.json` each time the launcher opens. It writes
`generated-colors.rasi` and the final import file into
`~/.cache/maho/launcher/` using a same-directory temporary file, `fsync`, and
atomic replacement.

The material starts from neutral graphite, then mixes in a very small amount of
the wallpaper environment. Primary color remains strongest at the selected tab,
selected result, and focus rim. Low-chroma palettes automatically collapse back
to neutral gray. Foreground and muted semantics are desaturated and
contrast-bounded so a colorful wallpaper cannot flood the whole launcher.

The generator emits separate top/base material stops for the panel, search,
segmented modes, active tab, and selected row. Rofi composites each gradient
once over the blurred backdrop; transparent base fills prevent accidental
double opacity. The outer panel runs at 76/80/82% from top through bottom,
while inset and selected surfaces remain more transparent so the hierarchy
comes from restrained depth rather than stacked opaque cards.

Five Palette V2 material fixtures are contract-tested and Rasi-parsed:

| Palette family | Panel RGBA | Selected row RGBA | Focus rim RGBA | Outcome |
| --- | --- | --- | --- | --- |
| Monochrome | 24/25/28/80 | 55/55/56/54 | 190/190/190/42 | neutral gray, no hue cast |
| Cool blue | 28/32/37/80 | 66/75/87/54 | 146/192/254/42 | cool reflected tint, blue focus |
| Warm orange | 31/29/31/80 | 75/63/59/54 | 254/180/146/42 | neutral panel, warm selected state |
| Pink/purple | 30/27/33/80 | 71/58/71/54 | 234/145/218/42 | restrained magenta reflection |
| Muted green | 27/29/29/80 | 62/66/55/54 | 175/190/119/42 | muted olive focus without green flood |

## Hyprland material

While Maho Launcher is open, its wrapper installs a named runtime-only
Hyprland layer rule with blur, `ignore_alpha = 0.06`, and `xray`. `xray` lets
the frosted surface sample the full backdrop instead of collapsing to a flat
fill over application windows. The rule is disabled on exit; no persistent
global blur setting or Maho Edge rule is modified.

Hyprland exposes blur kernel size, pass count, noise, contrast, and vibrancy as
global decoration settings rather than per-layer rule properties. Maho
Launcher therefore inherits the user's compositor blur kernel and limits its
own changes to the scoped `rofi` layer rule. This preserves system ownership
while producing the strongest launcher-local material the installed compositor
API supports.

Rofi 2.0 exposes the fixed Wayland layer namespace `rofi` and does not provide a
per-invocation namespace flag. Consequently the temporary material rule can
also affect another Rofi surface opened concurrently during the short lifetime
of Maho Launcher. The wrapper's dedicated pid file and lock still isolate
process ownership and never kill unrelated Rofi processes. A future Rofi
namespace option would remove this remaining compositor-scope limitation.

## Commands and diagnostics

```text
maho-launcher open
maho-launcher toggle
maho-launcher close
maho-launcher status
maho-launcher doctor
maho-launcher reload
maho-launcher logs [LINES]
```

The runtime log records lifecycle and engine errors only. It never records user
queries. `doctor` checks Rofi, atomic palette conversion, Rasi parsing, safe
mode scripts, singleton state, and compositor capability.

## Maho Edge and rollback

The only Maho Edge integration change is its fixed launcher invocation:

```text
~/.local/bin/maho-launcher open
```

Edge geometry, input/drag behavior, `DockReservation`, exclusive zone,
breathing room, workspace rail, control-center choreography, notification
integration, and Maho Themes are untouched.

The acceptance install intentionally does not own, replace, or remove
`~/.local/bin/maho-rice-launcher`. On the development system that remains the
old working Rofi rollback command and continues to use
`~/.config/maho-rice/launcher/launcher.rasi`. The global launcher keybind is
also intentionally unchanged until visual approval.

Repository rollback is a normal revert of the production branch commits. The
safety ref `safety/maho-launcher-rofi-base` points to the exact selected base.

## Runtime acceptance (2026-08-24)

The production path was exercised in the live Hyprland 0.56.2 session with
native Wayland Rofi 2.0.0. Apps search, clear, Up/Down, Return activation,
Escape, Files, Commands, paging, icon resolution, and the exact production
`drun` execution path were checked. `Thunar File Manager` launched through the
production Rofi arguments, covering a GTK app, a spaced desktop-entry name,
secondary metadata, and a real installed icon. Electron entries (Vesktop and
ChatGPT), OBS Studio, and unusual entries/icons were discovered from the 38
installed desktop entries. Flatpak is not installed, so no Flatpak application
was available for coverage.

Measured from wrapper start until the owned Rofi PID became live after the
material update, the first process-visible open was 123 ms. Five subsequent
opens measured 115–147 ms (124.8 ms mean). Rofi RSS was 20,112 KiB. The prior
baseline was 117 ms cold, 127.4 ms warm mean, and 20,176 KiB RSS, so the visual
material introduced no meaningful launch-time or memory regression. Fifty
automated open/close cycles completed with zero failures, no remaining PID,
and no zombie Rofi process. A concurrent second invocation returned
`maho-launcher: already running`.

Five generated Palette V2 fixtures (monochrome, cool blue, warm orange,
pink/purple, and muted green) passed atomic generation, material invariants,
and live Rasi parsing. The cool fixture was rendered over a detailed wallpaper
with the production layer rule for the final normalized Reference A comparison
recorded in `design-qa.md`.

The installed acceptance bridge was validated as a live fixed command and the
Edge surface remained responsive after launcher cycles. This environment has
no virtual pointer device available, and Hyprland's shortcut dispatcher sends
mouse buttons to the focused client rather than synthesizing a compositor
pointer click. Therefore an automated physical Edge click is the one remaining
runtime test limitation; the visible Edge hit target and exact QML invocation
seam were verified independently. No global keybind was changed.
