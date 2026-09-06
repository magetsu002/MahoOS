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
            "preview": "Pinned-row render proof",
            "type": "Text",
            "search": "pinned-row render proof",
            "pinned": false,
            "pinKey": ""
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

    function test_real_delegate_contains_visible_clickable_pin() {
        var glyph = findChild(panel, "clipboardPinGlyph")
        tryVerify(function() { return glyph !== null }, 1000,
                  "real ClipboardPanel delegate never instantiated its pin glyph")

        verify(glyph.visible)
        verify(glyph.opacity > 0.9)
        verify(glyph.geometryReady)
        compare(glyph.width, 17)
        compare(glyph.height, 17)

        var button = glyph.parent
        verify(button !== null)
        compare(button.width, 34)
        compare(button.height, 34)
        verify(button.visible)
        verify(button.opacity > 0.9)

        mouseClick(button, button.width / 2, button.height / 2, Qt.LeftButton)
        compare(fakeState.toggleCalls, 1)
        compare(fakeState.selectCalls, 0)
    }
}
