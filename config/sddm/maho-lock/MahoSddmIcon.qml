import QtQuick 2.15

Item {
    id: root

    property string name: "lock"
    property real iconOpacity: 0.92

    Image {
        anchors.fill: parent
        source: "assets/icons/" + root.name + ".svg"
        opacity: root.iconOpacity
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
        asynchronous: false
        sourceSize.width: Math.max(64, Math.ceil(width * 4))
        sourceSize.height: Math.max(64, Math.ceil(height * 4))
    }
}
