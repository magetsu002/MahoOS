import QtQuick
import QtTest
import "../config/quickshell/maho-shell/DockPreviewPolicy.js" as DockPreviewPolicy

TestCase {
    name: "MahoDockPreviewPolicy"

    function row(address, focused, mru) {
        return {"address": address, "activated": focused, "mru": mru}
    }

    function addresses(rows) {
        const output = []
        for (let index = 0; index < rows.length; ++index)
            output.push(rows[index].address)
        return output.join(",")
    }

    function test_one_window() {
        compare(addresses(DockPreviewPolicy.selectWindows([
            row("one", false, 1)
        ], 3)), "one")
    }

    function test_two_windows_rank_focused_first() {
        compare(addresses(DockPreviewPolicy.selectWindows([
            row("older", false, 30),
            row("focused", true, 1)
        ], 3)), "focused,older")
    }

    function test_three_windows_rank_mru_after_focus() {
        compare(addresses(DockPreviewPolicy.selectWindows([
            row("oldest", false, 1),
            row("newest", false, 9),
            row("focused", true, 2)
        ], 3)), "focused,newest,oldest")
    }

    function test_more_than_three_is_capped_deterministically() {
        const selected = DockPreviewPolicy.selectWindows([
            row("window-e", false, 2),
            row("window-b", false, 8),
            row("window-d", false, 4),
            row("window-a", true, 1),
            row("window-c", false, 6)
        ], 3)
        compare(selected.length, 3)
        compare(addresses(selected), "window-a,window-b,window-c")
    }
}
