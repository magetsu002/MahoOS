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
- the Maho copies match the geometry shipped by Arch Linux `adwaita-icon-theme 50.0-1`, sourced from upstream tag `50.0` (peeled commit `551245ae75fdc42cde42a8cf24ca2ccab9d3a815`), with formatting/foreground adaptation for the Maho SDDM theme
- Arch Linux declares the upstream package license expression as **CC-BY-SA-3.0 OR LGPL-3.0-only**

MahoOS selects the **LGPL-3.0-only** option for redistribution of these two adapted icons. The upstream dual-license notice is preserved in `LICENSES/Adwaita-COPYING.txt`, and the canonical LGPL v3 text is preserved in `LICENSES/LGPL-3.0-only.txt`. The repository root `LICENSE` provides the GNU GPL v3 text incorporated by LGPL v3. Attribution: **GNOME Project** — https://www.gnome.org/.

The exact historical upstream commit used at the moment of the original Maho adaptation was not recorded. For reproducible provenance, the current verification binds the matching icon geometry to upstream tag `50.0`, peeled commit `551245ae75fdc42cde42a8cf24ca2ccab9d3a815`.

## Guardian prototype sounds

Bundled material:

- `config/quickshell/maho-shell/sounds/guardian-stage.wav`
- `config/quickshell/maho-shell/sounds/guardian-catastrophic.wav`

Both bundled WAVs are processed derivatives of CC0 sounds by **ani_music** on Freesound:

- `guardian-stage.wav` derives from **“Steel chain dragged, shower reverb”**, Freesound sound 167914: https://freesound.org/people/ani_music/sounds/167914/
- `guardian-catastrophic.wav` derives from **“Hard steel chain plate drop”**, Freesound sound 167917: https://freesound.org/people/ani_music/sounds/167917/

License: **Creative Commons CC0**.

The conversion/source record is also stored at `config/quickshell/maho-shell/sounds/SOURCE.txt`.

## Project-generated Guardian rotor

Bundled material:

- `config/quickshell/maho-shell/maho-guardian-rotor.png`

The rotor artwork was created specifically for the MahoOS Guardian wheel during MahoOS development and was not imported from an identified external asset source. It should follow the project-wide license selected for MahoOS once that license is decided.

## Bundled visual assets with provenance still to confirm

### Lock fallback wallpaper

- `config/quickshell/maho-lock/assets/maho-lock-dusk.jpg`

The accepted 1672×941 JPEG was restored from MahoOS development work after an earlier corrupt fallback was discovered, but the original creator/source/license of the JPEG was not recorded. Before public release, confirm ownership/provenance or replace the fallback with an asset whose rights are known.

### Kurisu terminal animation

- `share/maho/terminal/kurisu-transparent.apng`
- conversion record: `share/maho/terminal/SOURCE.txt`

The APNG was produced during the pre-Maho terminal setup from a cleaned animated source file named `kurisu-spinning-Picsart-BackgroundRemover.webm`, via extracted PNG frames and FFmpeg APNG encoding. That establishes the local conversion lineage only.

The original animation/artwork source, creator, and redistribution license are not documented. Because Kurisu Makise is third-party character artwork, do not treat the conversion itself as permission to redistribute the underlying art. Before public release, establish a redistribution source/license or replace/remove this bundled animation.

## Project license

Unless otherwise stated, original MahoOS code is licensed under the **GNU General Public License version 3 only (GPL-3.0-only)**. The canonical license text is in the repository root `LICENSE`.

That default does not override file-specific or third-party terms. In particular, existing Prevention C/BPF files carrying `SPDX-License-Identifier: GPL-2.0` retain that existing GPL v2-only declaration; the VM root-destruction verifier remains MIT; SDDM metadata carrying `GPL-3.0-or-later` remains under that declaration; Nunito remains SIL OFL 1.1; the Guardian sounds remain CC0; and the Adwaita-derived icons use the LGPL-3.0-only redistribution option recorded above.
