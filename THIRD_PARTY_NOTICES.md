# Third-party notices

This file inventories third-party or provenance-sensitive material bundled directly in the MahoOS repository. It does **not** list operating-system or package-manager dependencies.

## Nunito

Bundled material:

- `config/quickshell/maho-lock/assets/Nunito-Variable.ttf`
- `config/quickshell/maho-lock/assets/Nunito-OFL.txt`

Copyright: 2014 The Nunito Project Authors.

License: **SIL Open Font License 1.1**.

The complete font license text is stored beside the bundled font in `Nunito-OFL.txt`.

## GNOME Adwaita-derived SDDM icons

Bundled material:

- `config/sddm/maho-lock/icons/restart.svg`
- `config/sddm/maho-lock/icons/session.svg`

The files identify themselves as adaptations of GNOME Adwaita `system-reboot-symbolic` and `video-display-symbolic` respectively.

Verified source family:

- upstream project: https://gitlab.gnome.org/GNOME/adwaita-icon-theme
- `restart.svg` follows `symbolic/actions/system-reboot-symbolic.svg`
- `session.svg` follows `symbolic/devices/video-display-symbolic.svg`
- the Maho copies match the geometry shipped by Arch Linux `adwaita-icon-theme 50.0-1`, with formatting/foreground adaptation for the Maho SDDM theme
- Arch Linux declares the upstream package license expression as **CC-BY-SA-3.0 OR LGPL-3.0-only**

The exact upstream Git commit used for the original adaptation was not recorded when the Maho files were added. Before public release, maintainers must choose the applicable upstream license branch and include any license/notice material required by that choice rather than silently relicensing the adapted icons.

## Guardian prototype sounds

Bundled material:

- `config/quickshell/maho-shell/sounds/guardian-stage.wav`
- `config/quickshell/maho-shell/sounds/guardian-catastrophic.wav`

Both bundled WAVs are processed derivatives of CC0 sounds by **ani_music** on Freesound:

- `guardian-stage.wav` derives from **“Steel chain dragged, shower reverb”**, Freesound sound 167914: https://freesound.org/people/ani_music/sounds/167914/
- `guardian-catastrophic.wav` derives from **“Hard steel chain plate drop”**, Freesound sound 167917: https://freesound.org/people/ani_music/sounds/167917/

License: **Creative Commons CC0**.

The conversion/source record is also stored at `config/quickshell/maho-shell/sounds/SOURCE.txt`.

## Bundled visual assets with provenance still to confirm

The repository currently does not record an external source, author, or license for these bundled visual assets:

- `config/quickshell/maho-lock/assets/maho-lock-dusk.jpg`
- `config/quickshell/maho-shell/maho-guardian-rotor.png`
- `share/maho/terminal/kurisu-transparent.apng`

Absence of an attribution record does not establish that an asset is third-party or project-owned. Before public release, maintainers must confirm that each asset is project-owned or add the correct source/author/license information. If provenance cannot be established, replace or remove the asset before publication.

## Project license

These notices are separate from the MahoOS project license. The project-wide license is intentionally still pending management selection.
