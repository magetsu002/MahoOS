# Maho Themes

Maho Themes is MahoOS's on-demand wallpaper browser and the graphical frontend
for the existing `maho-theme` Palette V2 engine. It preserves the proven
carousel, thumbnail browsing, local filtering, keyboard and mouse controls,
animated video previews, and explicit Wallhaven search from the user's working
wallpaper picker. It remains independent of Maho Edge, Maho Notify, and Maho
Launcher.

## Origin and license

The UI and discovery pipeline were adopted from
`https://github.com/magetsu002/qs-wallpaper-picker` at commit
`c81fe1d4c3485b7dc39e0cd0aa82ccc6228ed9f6`. That repository is maintained by
Magetsu and distributed under the MIT License. The required copyright and
license notice is preserved in `config/quickshell/maho-themes/UPSTREAM-LICENSE`.
The upstream README, including the original ilyamiro interface attribution and
contributor credits, is preserved as `UPSTREAM.md`.

The source checkout used for adoption had a local modification to
`WallpaperPicker.qml` that attempted to call Maho after the existing wallpaper
setter. It was not copied verbatim: Maho Themes implements the same intent with
direct argument arrays and one verified wallpaper/palette transaction. The
original checkout, cache, keybindings, and runtime files are not removed or
rewired by this milestone.

## Palette and transaction model

`~/.cache/maho/theme/active.json` is the only active Maho palette. Maho Themes
reads it through a watchable, side-effect-free Quickshell `FileView`; rendering
never applies a wallpaper or regenerates colors.

`maho-theme apply WALLPAPER [dark|light]` performs the combined transaction:

1. validate the wallpaper and generate a Palette V2 candidate;
2. capture the current `awww` or `mpvpaper` wallpaper identity and active
   palette;
3. apply and verify the selected wallpaper using the existing backend;
4. apply and verify the candidate palette in Hyprland;
5. atomically publish `active.json` and Maho wallpaper state;
6. resume the related wallpaper observer and re-verify the committed pair;
7. restore and verify the previous wallpaper and palette if a later step fails.

If the managed `maho-wallpaper.service` is active, the transaction pauses only
that related observer during the bounded mutation and restores its prior active
posture before returning. This prevents an older installed observer from racing
manual acceptance of a newer Maho Themes checkout.

Wallpaper files are referenced by stable real paths; they are not copied into
transaction history. Video palettes are generated from a bounded extracted
frame while the original video identity remains the wallpaper state.

## Commands and runtime state

- `maho-theme open` opens the single-instance Maho Themes UI.
- `maho-theme doctor` reports UI, wallpaper backend, palette backend, and active
  palette availability.
- `maho-theme generate WALLPAPER [dark|light]` creates a candidate only.
- `maho-theme apply WALLPAPER [dark|light]` commits wallpaper and palette.
- `maho-theme show` and `maho-theme hash` inspect the current candidate.
- `maho-theme apply-hypr` and `maho-theme restore-hypr` preserve their existing
  palette-only behavior.

Maho Themes stores thumbnails and UI cache below
`$XDG_CACHE_HOME/maho/themes`, transaction status below
`$XDG_STATE_HOME/maho/themes`, and the canonical palette below
`$XDG_CACHE_HOME/maho/theme`. The first launch may seed reusable thumbnail data
from the old picker cache, but never moves or deletes that cache.
When `QS_WALLPAPER_DIR` is unset, `maho-theme open` discovers the collection
from the current wallpaper and then falls back to `$HOME/Pictures/Wallpapers`
before using the upstream `$HOME/Wallpapers` default.

Run manually from a checkout with:

```bash
MAHO_ROOT=/path/to/MahoOS bash /path/to/MahoOS/bin/maho-theme open
```

## Rollback and deferred work

Each integration commit is additive and can be reverted with `git revert`.
Runtime apply failures use the captured state automatically. The original
wallpaper picker remains the manual rollback surface until Maho Themes receives
visual approval.

Deliberately deferred work includes an Edge button, Launcher-specific patches,
Notify success messages, per-monitor themes, a larger settings surface, and a
premium visual redesign.
