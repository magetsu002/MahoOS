import QtQuick
import "WindowRegistry.js" as LayoutMath 

QtObject {
    id: root

    property real currentWidth: 1920.0
    property real baseScale: LayoutMath.getScale(currentWidth)
    function s(val) { 
        return LayoutMath.s(val, baseScale); 
    }
}
