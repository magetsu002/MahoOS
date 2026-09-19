import QtQuick
import Quickshell
import Quickshell.Wayland

PanelWindow {
    id: root

    anchors {
        top: true
        bottom: true
        left: true
        right: true
    }

    color: "transparent"
    focusable: false
    exclusionMode: ExclusionMode.Ignore
    aboveWindows: true
    mask: Region { item: root.presentationActive ? stage : null }

    WlrLayershell.namespace: "maho-guardian-overlay"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    property bool presentationActive: false
    property int lastGuardianGeneration: 0

    signal catastrophicLocked()

    GuardianState {
        id: guardianState
        enabled: true
    }

    function presentationDuration(severity) {
        if (severity >= 4) return 5600
        if (severity === 3) return 3600
        if (severity === 2) return 2700
        return 1800
    }

    function presentGuardian() {
        if (!guardianState.presentable) {
            presentationTimer.stop()
            presentationActive = false
            guardianWheel.resetHidden()
            return
        }

        if (guardianState.generation <= lastGuardianGeneration)
            return

        lastGuardianGeneration = guardianState.generation
        presentationActive = true
        presentationTimer.interval = presentationDuration(guardianState.highestSeverity)
        presentationTimer.restart()
        guardianWheel.resetHidden()
        guardianWheel.advanceIfNeeded()
    }

    Timer {
        id: presentationTimer
        interval: 1800
        repeat: false
        onTriggered: {
            root.presentationActive = false
            guardianWheel.resetHidden()
        }
    }

    Rectangle {
        id: stage
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: 72

        width: 116
        height: 84
        radius: 28

        color: Qt.rgba(0.04, 0.04, 0.05, 0.94)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.12)

        visible: opacity > 0.01
        opacity: root.presentationActive ? 1 : 0
        scale: root.presentationActive ? 1 : 0.96

        Behavior on opacity { NumberAnimation { duration: 120 } }
        Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }

        GuardianWheel {
            id: guardianWheel
            anchors.centerIn: parent
            width: 54
            height: 54
            active: root.presentationActive
            targetSeverity: guardianState.highestSeverity
            catastrophicTransitionSerial: guardianState.catastrophicTransitionSerial
            onCatastrophicLocked: root.catastrophicLocked()
        }
    }

    Connections {
        target: guardianState

        function onGenerationChanged() {
            root.presentGuardian()
        }

        function onHighestSeverityChanged() {
            if (!guardianState.presentable) {
                presentationTimer.stop()
                root.presentationActive = false
                guardianWheel.resetHidden()
            } else if (root.presentationActive) {
                presentationTimer.interval = root.presentationDuration(guardianState.highestSeverity)
                presentationTimer.restart()
                guardianWheel.advanceIfNeeded()
            }
        }
    }
}
