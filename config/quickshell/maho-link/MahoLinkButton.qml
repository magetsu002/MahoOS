import QtQuick

Rectangle {
    id: root
    required property var chrome
    required property string label
    property bool primary: false
    property bool destructive: false
    signal clicked()

    height: 43
    radius: 13
    color: !enabled
        ? chrome.theme.alpha(chrome.insetColor, 0.52)
        : primary
            ? chrome.theme.alpha(chrome.accent, hover.containsMouse ? 0.93 : 0.83)
            : hover.containsMouse
                ? chrome.mix(chrome.insetColor, chrome.accent, 0.10)
                : chrome.theme.alpha(chrome.insetColor, 0.78)
    border.width: 1
    border.color: primary
        ? chrome.theme.alpha(chrome.accent, 0.50)
        : chrome.theme.alpha(destructive ? chrome.theme.error : chrome.theme.outline, hover.containsMouse ? 0.30 : 0.16)
    opacity: enabled ? 1 : 0.46

    Text {
        anchors.centerIn: parent
        text: root.label
        color: root.destructive ? chrome.theme.error
            : root.primary ? Qt.rgba(1, 1, 1, 0.96) : chrome.textPrimary
        font.family: "Inter"
        font.pixelSize: 13
        font.weight: Font.DemiBold
    }

    MouseArea {
        id: hover
        anchors.fill: parent
        enabled: root.enabled
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }

    Behavior on color { ColorAnimation { duration: 120 } }
}
