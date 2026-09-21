#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_DATA_HOME="$TMP/share"
export XDG_CONFIG_HOME="$TMP/config"
export PATH="$TMP/bin:$PATH"

mkdir -p "$HOME" "$XDG_DATA_HOME/maho/runtime" "$XDG_CONFIG_HOME" "$TMP/bin"
ln -s "$ROOT" "$XDG_DATA_HOME/maho/runtime/current"

cat >"$TMP/bin/xdg-mime" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = query ]; then
    printf 'vesktop.desktop\n'
else
    printf '%s\n' "$*" >>"${XDG_CONFIG_HOME}/xdg-mime.calls"
fi
EOF
chmod 0755 "$TMP/bin/xdg-mime"
cat >"$TMP/bin/update-desktop-database" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod 0755 "$TMP/bin/update-desktop-database"

bash "$ROOT/bin/maho-vesktop-install" install
bash "$ROOT/bin/maho-vesktop-install" status

WRAPPER="$HOME/.local/bin/vesktop-guard"
DESKTOP="$XDG_DATA_HOME/applications/vesktop.desktop"

grep -Fqx '# managed-by: maho-vesktop-install v1' "$WRAPPER"
grep -Fqx 'RUNTIME="${XDG_DATA_HOME:-$HOME/.local/share}/maho/runtime/current"' "$WRAPPER"
grep -Fqx "Exec=$WRAPPER %U" "$DESKTOP"
grep -Fqx 'Terminal=false' "$DESKTOP"
grep -Fqx 'Type=Application' "$DESKTOP"
grep -Fqx 'MimeType=x-scheme-handler/discord;' "$DESKTOP"
grep -Fqx 'default vesktop.desktop x-scheme-handler/discord' "$XDG_CONFIG_HOME/xdg-mime.calls"

bash "$ROOT/bin/maho-vesktop-install" uninstall
[ ! -e "$WRAPPER" ]
[ ! -e "$DESKTOP" ]

echo "PASS Vesktop canonical install contracts"