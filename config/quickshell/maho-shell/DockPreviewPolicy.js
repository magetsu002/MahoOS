.pragma library

function asNumber(value) {
    const numeric = Number(value || 0)
    return isFinite(numeric) ? numeric : 0
}

function address(value) {
    return String(value && value.address ? value.address : "")
}

function compareWindows(first, second) {
    const firstFocused = Boolean(first && first.activated)
    const secondFocused = Boolean(second && second.activated)
    if (firstFocused !== secondFocused)
        return firstFocused ? -1 : 1

    const firstMru = asNumber(first && first.mru)
    const secondMru = asNumber(second && second.mru)
    if (firstMru !== secondMru)
        return secondMru - firstMru

    return address(first).localeCompare(address(second))
}

function selectWindows(windows, maximum) {
    if (!windows)
        return []
    const ranked = []
    const count = Math.max(0, Number(windows.length || 0))
    for (let index = 0; index < count; ++index)
        ranked.push(windows[index])
    ranked.sort(compareWindows)
    return ranked.slice(0, Math.max(0, Number(maximum || 0)))
}
