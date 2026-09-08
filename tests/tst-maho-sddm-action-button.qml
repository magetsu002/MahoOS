import QtQuick
import QtQuick.Window
import QtTest
import "../config/sddm/maho-lock"

TestCase {
    id: testCase
    name: "MahoSddmActionButton"
    when: host.visible

    property int triggerCount: 0

    Window {
        id: host
        width: 360
        height: 180
        visible: true
        color: "#17375f"

        MahoSddmActionButton {
            id: button
            anchors.centerIn: parent
            uiScale: 1.6
            controlWidth: 128
            iconName: "power"
            label: "Sleep"
            onTriggered: testCase.triggerCount += 1
        }
    }

    function init() {
        triggerCount = 0
        mouseMove(host, 2, 2)
        wait(180)
    }

    function test_preview_equivalent_physical_size() {
        compare(button.width, 204.8)
        compare(button.height, 83.2)
    }

    function test_pointer_hover_and_click_are_live() {
        verify(!button.hovered)
        mouseMove(button, button.width / 2, button.height / 2)
        tryVerify(function() { return button.hovered }, 500)
        tryCompare(button, "scale", 1.025, 500)

        mouseClick(button, button.width / 2, button.height / 2, Qt.LeftButton)
        compare(triggerCount, 1)
    }

    function test_disabled_action_cannot_trigger() {
        button.enabled = false
        mouseClick(button, button.width / 2, button.height / 2, Qt.LeftButton)
        compare(triggerCount, 0)
        button.enabled = true
    }
}
