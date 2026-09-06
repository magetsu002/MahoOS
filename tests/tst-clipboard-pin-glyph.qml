import QtQuick
import QtTest
import "../config/quickshell/maho-clipboard"

TestCase {
    name: "ClipboardPinGlyph"

    ClipboardPinGlyph {
        id: glyph
        width: 17
        height: 17
        glyphColor: "#f2f2f2"
    }

    function test_geometry_is_instantiated_and_visible() {
        compare(glyph.width, 17)
        compare(glyph.height, 17)
        verify(glyph.visible)
        verify(glyph.opacity > 0)
        verify(glyph.geometryReady)
        verify(glyph.children.length > 0)
    }

    function test_color_reaches_render_geometry() {
        compare(glyph.renderedColor, glyph.glyphColor)
        glyph.glyphColor = "#91a7ff"
        wait(0)
        compare(glyph.renderedColor, glyph.glyphColor)
    }
}
