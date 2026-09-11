import QtQuick
import QtQuick.Window
import QtTest
import "../config/quickshell/maho-shell"

TestCase {
    name: "MahoFallbackAppGlyph"
    when: host.visible

    Window {
        id: host
        width: 96
        height: 96
        visible: true
        color: "#202124"

        MahoFallbackAppGlyph {
            id: fallback
            anchors.centerIn: parent
            width: 48
            height: 48
            glyphColor: "#f4f4f4"
        }
    }

    function test_vector_geometry_is_ready() {
        verify(fallback.visible)
        verify(fallback.geometryReady)
        compare(fallback.width, 48)
        compare(fallback.height, 48)
    }
}
