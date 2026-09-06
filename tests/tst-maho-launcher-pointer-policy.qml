import QtQuick
import QtTest
import "../config/quickshell/maho-launcher/PointerSelectionPolicy.js" as PointerSelectionPolicy

TestCase {
    name: "MahoLauncherPointerPolicy"

    function test_fresh_open_ignores_passive_pointer_over_result_five() {
        let selected = PointerSelectionPolicy.topIndex(8)
        compare(selected, 0)
        selected = PointerSelectionPolicy.hoverIndex(selected, 4, false)
        compare(selected, 0)
    }

    function test_immediate_enter_still_targets_top_result() {
        const selected = PointerSelectionPolicy.topIndex(8)
        compare(selected, 0)
    }

    function test_real_pointer_movement_grants_hover_authority() {
        verify(!PointerSelectionPolicy.movedEnough(100, 100, 102, 101, 4))
        verify(PointerSelectionPolicy.movedEnough(100, 100, 105, 100, 4))
        compare(PointerSelectionPolicy.hoverIndex(0, 4, true), 4)
    }

    function test_click_is_immediate_without_hover_authority() {
        compare(PointerSelectionPolicy.clickIndex(4), 4)
    }
}
