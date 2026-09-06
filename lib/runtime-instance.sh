#!/usr/bin/env bash

# Shared read-only process identity helpers for transient Quickshell products.
# Product launchers remain responsible for their own exact IPC and lifecycle.

maho_runtime_identity() {
    readlink -f -- "$1"
}

maho_process_runtime_identity() {
    local pid="$1" entry
    [ -r "/proc/$pid/environ" ] || return 1
    while IFS= read -r entry; do
        case "$entry" in
            MAHO_RUNTIME_IDENTITY=*)
                printf '%s\n' "${entry#MAHO_RUNTIME_IDENTITY=}"
                return 0
                ;;
        esac
    done < <(tr '\0' '\n' < "/proc/$pid/environ")
    return 1
}

maho_quickshell_config_pids() {
    local suffix="$1" pid argument matched
    while read -r pid; do
        [ -r "/proc/$pid/cmdline" ] || continue
        matched=0
        while IFS= read -r argument; do
            case "$argument" in
                *"$suffix")
                    matched=1
                    break
                    ;;
            esac
        done < <(tr '\0' '\n' < "/proc/$pid/cmdline")
        [ "$matched" -eq 1 ] && printf '%s\n' "$pid"
    done < <({ pgrep -x quickshell 2>/dev/null; pgrep -x qs 2>/dev/null; } | sort -u)
}

maho_wait_for_process_exit() {
    local pid="$1" attempts="${2:-20}"
    while [ "$attempts" -gt 0 ]; do
        kill -0 "$pid" 2>/dev/null || return 0
        sleep 0.05
        attempts=$((attempts - 1))
    done
    return 1
}
