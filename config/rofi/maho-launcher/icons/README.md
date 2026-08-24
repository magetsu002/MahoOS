# Launcher icon assets

Maho Launcher now resolves its header, search, and chevron chrome from scalable
symbolic icon-theme names at runtime (`view-app-grid-symbolic`,
`preferences-system-symbolic`, `system-search-symbolic`, `go-next-symbolic`,
`go-down-symbolic`, and `go-up-symbolic`). Rofi resolves those names through the
active icon theme/GdkPixbuf so fractional Wayland scaling does not depend on a
pre-rendered bitmap size.

The PNG files in this directory are retained only as historical/fallback assets
from the first production pass. They are derived from Adwaita icons shipped on
the development system and are not used by the normal generated runtime theme.
Application icons remain the native icons supplied by installed desktop entries;
Maho does not recolor or replace application branding.

Adwaita icons are distributed by the GNOME project under the terms documented
with the installed icon package. Maho does not claim authorship of them.
