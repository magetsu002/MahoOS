import QtQuick

// One geometric contract for every Bluetooth/device logo in Maho Link.
// The glyph line box fills the icon container, so its horizontal and vertical
// centers are exactly the container center. Individual surfaces must not add
// baseline nudges or implicit-size positioning.
Item {
    id: root

    required property string symbol
    required property color glyphColor
    property int pixelSize: 18

    Text {
        anchors.fill: parent
        text: root.symbol
        color: root.glyphColor
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: root.pixelSize
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        renderType: Text.NativeRendering
    }
}
