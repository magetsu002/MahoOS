import QtQuick
import Quickshell

Item {
    id: root

    property bool active: false
    property int targetSeverity: 0
    property int catastrophicTransitionSerial: 0

    property int _displayedSeverity: 0
    property real _angle: 0
    property bool _animating: false
    property bool _lockedIn: false
    property int _handledCatastrophicSerial: 0

    property real _wheelScale: 1.0
    property real _impactOpacity: 0.0
    property real _impactScale: 1.0

    property real _secondImpactOpacity: 0.0
    property real _secondImpactScale: 1.0

    signal stageLocked(int severity)
    signal catastrophicLocked()

    implicitWidth: 42
    implicitHeight: 42

    readonly property string stageSoundUrl:
        Qt.resolvedUrl("sounds/guardian-stage.wav").toString()

    readonly property string catastrophicSoundUrl:
        Qt.resolvedUrl("sounds/guardian-catastrophic.wav").toString()

    function fileUrlToPath(url) {
        const value = String(url)

        if (value.startsWith("file://"))
            return decodeURIComponent(value.slice(7))

        return decodeURIComponent(value)
    }

    function playLockSound(severity) {
        const url = severity === 4
            ? catastrophicSoundUrl
            : stageSoundUrl

        const path = fileUrlToPath(url)

        Quickshell.execDetached([
            "pw-play",
            path
        ])
    }

    function clampSeverity(v) {
        return Math.max(0, Math.min(4, Math.round(v)))
    }

    function advanceIfNeeded() {
        if (!active || _animating)
            return

        const wanted = clampSeverity(targetSeverity)

        if (_displayedSeverity >= wanted)
            return

        _animating = true
        preTurn.restart()
    }

    function resetHidden() {
        _displayedSeverity = 0
        _angle = 0
        _animating = false
        _lockedIn = false

        _wheelScale = 1
        _impactOpacity = 0
        _impactScale = 1
        _secondImpactOpacity = 0
        _secondImpactScale = 1
    }

    onTargetSeverityChanged: advanceIfNeeded()
    onActiveChanged: if (active) advanceIfNeeded()

    // ============================================================
    // MAIN APPROVED WHEEL
    // ============================================================

    Image {
        id: wheel
        anchors.fill: parent

        source: Qt.resolvedUrl("maho-guardian-rotor.png")
        fillMode: Image.PreserveAspectFit

        smooth: true
        mipmap: true

        scale: root._wheelScale

        transform: Rotation {
            origin.x: wheel.width / 2
            origin.y: wheel.height / 2
            angle: root._angle
        }
    }

    // ============================================================
    // IMPACT FRAME 1
    // exact same wheel, larger for a few frames
    // ============================================================

    Image {
        id: impactOne
        anchors.fill: parent

        source: Qt.resolvedUrl("maho-guardian-rotor.png")
        fillMode: Image.PreserveAspectFit

        smooth: true
        mipmap: true

        opacity: root._impactOpacity
        scale: root._impactScale

        transform: Rotation {
            origin.x: impactOne.width / 2
            origin.y: impactOne.height / 2
            angle: root._angle
        }
    }

    // Catastrophic only: second afterimage of SAME wheel.
    Image {
        id: impactTwo
        anchors.fill: parent

        source: Qt.resolvedUrl("maho-guardian-rotor.png")
        fillMode: Image.PreserveAspectFit

        smooth: true
        mipmap: true

        opacity: root._secondImpactOpacity
        scale: root._secondImpactScale

        transform: Rotation {
            origin.x: impactTwo.width / 2
            origin.y: impactTwo.height / 2
            angle: root._angle
        }
    }

    Timer {
        id: preTurn
        interval: 150
        repeat: false

        onTriggered: {
            const next = root._displayedSeverity + 1
            turnForward.to = next * 90 + 3
            turnForward.duration = next === 4 ? 430 : 340
            turnForward.start()
        }
    }

    // Fast mechanical movement with 3° overshoot.
    NumberAnimation {
        id: turnForward

        target: root
        property: "_angle"

        easing.type: Easing.OutQuart

        onFinished: {
            const exact = (root._displayedSeverity + 1) * 90

            settleTurn.to = exact
            settleTurn.start()
        }
    }

    // Tiny exact mechanical lock.
    NumberAnimation {
        id: settleTurn

        target: root
        property: "_angle"

        duration: 90
        easing.type: Easing.OutCubic

        onFinished: {
            root._displayedSeverity += 1

            // L4 impact/audio only fires for a real observed severity transition.
            if (root._displayedSeverity === 4) {
                if (root.catastrophicTransitionSerial > root._handledCatastrophicSerial) {
                    root._handledCatastrophicSerial = root.catastrophicTransitionSerial
                    root.playLockSound(4)
                    catastrophicImpact.restart()
                } else {
                    root._animating = false
                    root.stageLocked(4)
                }
            } else {
                root.playLockSound(root._displayedSeverity)
                normalImpact.restart()
            }
        }
    }

    // ============================================================
    // SEVERITY 1–3
    //
    // Very readable ~180 ms landing.
    // ============================================================

    SequentialAnimation {
        id: normalImpact

        ScriptAction {
            script: {
                root._wheelScale = 0.94
                root._impactScale = 1.16
                root._impactOpacity = 0.82
            }
        }

        PauseAnimation { duration: 85 }

        ParallelAnimation {
            NumberAnimation {
                target: root
                property: "_wheelScale"
                to: 1
                duration: 130
                easing.type: Easing.OutCubic
            }

            NumberAnimation {
                target: root
                property: "_impactOpacity"
                to: 0
                duration: 125
                easing.type: Easing.OutCubic
            }

            NumberAnimation {
                target: root
                property: "_impactScale"
                to: 1.23
                duration: 125
                easing.type: Easing.OutCubic
            }
        }

        onFinished: {
            root._wheelScale = 1
            root._impactOpacity = 0
            root._impactScale = 1

            root._animating = false

            root.stageLocked(root._displayedSeverity)
            root.advanceIfNeeded()
        }
    }

    // ============================================================
    // SEVERITY 4 — CATASTROPHIC
    //
    // Huge but still clean.
    // Only exact-wheel afterimages.
    // ============================================================

    SequentialAnimation {
        id: catastrophicImpact

        // HARD LANDING
        ScriptAction {
            script: {
                root._wheelScale = 0.90

                root._impactScale = 1.24
                root._impactOpacity = 1.0

                root._secondImpactScale = 1.38
                root._secondImpactOpacity = 0.38
            }
        }

        PauseAnimation { duration: 105 }

        ParallelAnimation {
            NumberAnimation {
                target: root
                property: "_wheelScale"
                to: 1
                duration: 175
                easing.type: Easing.OutCubic
            }

            NumberAnimation {
                target: root
                property: "_impactOpacity"
                to: 0
                duration: 170
                easing.type: Easing.OutCubic
            }

            NumberAnimation {
                target: root
                property: "_impactScale"
                to: 1.34
                duration: 170
            }

            NumberAnimation {
                target: root
                property: "_secondImpactOpacity"
                to: 0
                duration: 205
                easing.type: Easing.OutCubic
            }

            NumberAnimation {
                target: root
                property: "_secondImpactScale"
                to: 1.50
                duration: 205
            }
        }

        // Silence between impact and final confirmation.
        PauseAnimation { duration: 105 }

        // SECOND smaller lock confirmation
        ScriptAction {
            script: {
                root._impactScale = 1.13
                root._impactOpacity = 0.72
            }
        }

        PauseAnimation { duration: 80 }

        ParallelAnimation {
            NumberAnimation {
                target: root
                property: "_impactOpacity"
                to: 0
                duration: 135
            }

            NumberAnimation {
                target: root
                property: "_impactScale"
                to: 1.22
                duration: 135
            }
        }

        onFinished: {
            root._wheelScale = 1
            root._impactOpacity = 0
            root._impactScale = 1
            root._secondImpactOpacity = 0
            root._secondImpactScale = 1

            root._animating = false
            root._lockedIn = true

            root.stageLocked(4)
            root.catastrophicLocked()
        }
    }
}
