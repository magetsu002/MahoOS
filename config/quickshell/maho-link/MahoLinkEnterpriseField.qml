import QtQuick

Rectangle {
    id: root

    required property var chrome
    property alias text: editor.text
    property string placeholder: ""
    property bool secret: false
    property bool fieldEnabled: true
    signal submitted()

    height: visible ? 52 : 0
    radius: 16
    antialiasing: true
    color: chrome.theme.alpha(
        chrome.mix(chrome.theme.surfaceHigh, chrome.theme.background, 0.56), 0.47)
    border.width: 1
    border.color: editor.activeFocus
        ? chrome.theme.alpha(chrome.accent, 0.26)
        : chrome.theme.alpha(chrome.theme.foreground, 0.055)
    opacity: fieldEnabled ? 1 : 0.48

    TextInput {
        id: editor
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        verticalAlignment: TextInput.AlignVCenter
        enabled: root.fieldEnabled
        activeFocusOnTab: true
        echoMode: root.secret ? TextInput.Password : TextInput.Normal
        passwordCharacter: "•"
        color: chrome.textPrimary
        selectionColor: chrome.theme.alpha(chrome.accent, 0.30)
        selectedTextColor: chrome.textPrimary
        font.family: "Inter"
        font.pixelSize: 12
        clip: true
        Keys.onReturnPressed: root.submitted()
    }

    Text {
        anchors.left: parent.left
        anchors.leftMargin: 16
        anchors.right: parent.right
        anchors.rightMargin: 16
        anchors.verticalCenter: parent.verticalCenter
        visible: editor.text.length === 0 && !editor.activeFocus
        text: root.placeholder
        color: chrome.theme.alpha(chrome.textSecondary, 0.58)
        elide: Text.ElideRight
        font.family: "Inter"
        font.pixelSize: 11
    }

    function focusEditor() {
        editor.forceActiveFocus()
    }
}
