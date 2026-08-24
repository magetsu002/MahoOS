#!/usr/bin/env bash

set -u

emit_row() {
    printf '%s\0display\x1f%s\0icon\x1f%s\0info\x1f%s\n' "$1" "$2" "$3" "$1"
}

if [ "${ROFI_RETV:-0}" -eq 0 ]; then
    printf '\0no-custom\x1ftrue\n'
    emit_row reload "Reload launcher theme — Regenerate colors from active.json" view-refresh reload
    emit_row diagnostics "Launcher diagnostics — Check the production Rofi integration" utilities-system-monitor diagnostics
    command -v kitty >/dev/null 2>&1 && emit_row terminal "Terminal — Open a terminal session" utilities-terminal terminal
    command -v thunar >/dev/null 2>&1 && emit_row files "File Manager — Browse files with Thunar" system-file-manager files
    command -v hyprlock >/dev/null 2>&1 && emit_row lock "Lock Screen — Secure this session" system-lock-screen lock
    exit 0
fi

LAUNCHER_COMMAND="${MAHO_LAUNCHER_COMMAND:-maho-launcher}"

case "${ROFI_INFO:-${1:-}}" in
    reload)
        bash "$LAUNCHER_COMMAND" reload >/dev/null 2>&1 || true
        ;;
    terminal)
        command -v kitty >/dev/null 2>&1 && coproc (kitty >/dev/null 2>&1)
        ;;
    files)
        command -v thunar >/dev/null 2>&1 && coproc (thunar "$HOME" >/dev/null 2>&1)
        ;;
    lock)
        command -v hyprlock >/dev/null 2>&1 && coproc (hyprlock >/dev/null 2>&1)
        ;;
    diagnostics)
        if command -v kitty >/dev/null 2>&1; then
            coproc (kitty --hold -e bash "$LAUNCHER_COMMAND" doctor >/dev/null 2>&1)
        fi
        ;;
esac
