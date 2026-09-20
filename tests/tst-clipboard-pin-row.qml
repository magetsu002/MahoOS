import QtQuick
import QtQuick.Window
import QtTest
import "../config/quickshell/maho-clipboard"

TestCase {
    id: testCase
    name: "ClipboardPinRow"
    when: host.visible

    QtObject {
        id: fakeTheme
        property color foreground: "#f2f2f2"
        property color muted: "#a0a0a0"
        property color primary: "#8da4ff"
        property color surfaceHigh: "#27282c"
        property color background: "#121316"

        function alpha(colorValue, amount) {
            return Qt.rgba(colorValue.r, colorValue.g, colorValue.b, amount)
        }
    }

    QtObject {
        id: fakeState
        property bool available: true
        property bool loading: false
        property bool mutating: false
        property string errorText: ""
        property var items: [{
            "id": "7",
            "preview": "Hover-only pin render proof",
            "type": "Text",
            "search": "hover-only pin render proof",
            "pinned": false,
            "pinKey": ""
        }, {
            "id": "pin:8",
            "preview": "Filled pin latch proof",
            "type": "Text",
            "search": "filled pin latch proof pinned",
            "pinned": true,
            "pinKey": "8"
        }]
        property int toggleCalls: 0
        property int selectCalls: 0
        signal selectionCopied()

        function refresh() {}
        function clearUnpinned() {}
        function togglePin(item) {
            toggleCalls += 1
            return true
        }
        function selectItem(itemId) {
            selectCalls += 1
            return true
        }
    }

    Window {
        id: host
        width: 510
        height: 590
        visible: true
        color: "transparent"

        ClipboardPanel {
            id: panel
            anchors.fill: parent
            theme: fakeTheme
            clipboardState: fakeState
            shown: true
        }
    }

    function init() {
        fakeState.toggleCalls = 0
        fakeState.selectCalls = 0
        panel.rebuildFilter()
        wait(0)
    }

    function test_real_delegate_reveals_clickable_pin_only_on_row_hover() {
        var button = findChild(panel, "clipboardPinButton-0")
        tryVerify(function() { return button !== null }, 1000,
                  "real ClipboardPanel delegate never instantiated its first pin button")

        var glyph = findChild(button, "clipboardPinGlyph")
        verify(glyph !== null)
        verify(glyph.geometryReady)
        compare(glyph.width, 17)
        compare(glyph.height, 17)

        verify(button !== null)
        compare(button.width, 34)
        compare(button.height, 34)
        verify(button.visible)
        tryVerify(function() { return button.opacity < 0.05 }, 500,
                  "pin action remains visible while its row is idle")

        var row = button.parent
        mouseMove(row, row.width / 2, row.height / 2)
        tryVerify(function() { return button.opacity > 0.9 }, 500,
                  "pin action did not appear when its row was hovered")

        mouseClick(button, button.width / 2, button.height / 2, Qt.LeftButton)
        compare(fakeState.toggleCalls, 1)
        compare(fakeState.selectCalls, 0)
    }

    function test_filled_pin_stays_visible_when_pointer_moves_elsewhere() {
        var pinnedButton = findChild(panel, "clipboardPinButton-1")
        tryVerify(function() { return pinnedButton !== null }, 1000,
                  "real ClipboardPanel delegate never instantiated its filled pin button")

        tryVerify(function() { return pinnedButton.opacity > 0.9 }, 500,
                  "filled pin is hidden while its row is idle")

        var firstButton = findChild(panel, "clipboardPinButton-0")
        verify(firstButton !== null)
        var firstRow = firstButton.parent
        mouseMove(firstRow, firstRow.width / 2, firstRow.height / 2)
        tryVerify(function() { return pinnedButton.opacity > 0.9 }, 500,
                  "filled pin disappeared while hovering another row")

        mouseMove(host, 4, 4)
        tryVerify(function() { return pinnedButton.opacity > 0.9 }, 500,
                  "filled pin disappeared after leaving the clipboard rows")
    }
}
