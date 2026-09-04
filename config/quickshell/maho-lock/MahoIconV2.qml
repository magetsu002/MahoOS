import QtQuick
import Quickshell

Item {
    id: root

    property string name: "lock"
    property real iconOpacity: 0.82

    Image {
        anchors.centerIn: parent
        width: parent.width
        height: parent.height
        source: Quickshell.shellPath("icons/" + root.name + ".svg")
        opacity: root.iconOpacity
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
        asynchronous: false
        sourceSize.width: Math.max(24, Math.ceil(width * 2))
        sourceSize.height: Math.max(24, Math.ceil(height * 2))
    }
}
