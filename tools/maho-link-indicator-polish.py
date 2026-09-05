#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one {label}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


root = Path(__file__).resolve().parents[1]
link = root / "config/quickshell/maho-link"

state = link / "BluetoothState.qml"
replace_once(
    state,
    "readonly property bool busy: snapshotProcess.running || actionProcess.running || cancelProcess.running",
    "readonly property bool busy: actionProcess.running || cancelProcess.running",
    "Bluetooth busy binding",
)


def polish(path: Path, status_id: str, active_expr: str, active_text: str, idle_text: str) -> None:
    replace_once(
        path,
        """            Row {\n                anchors.right: parent.right\n                anchors.verticalCenter: parent.verticalCenter\n                spacing: 7\n""",
        """            Row {\n                anchors.right: parent.right\n                anchors.verticalCenter: parent.verticalCenter\n                height: 18\n                spacing: 7\n""",
        "status row",
    )

    replace_once(
        path,
        f"""                Rectangle {{\n                    width: 7\n                    height: 7\n                    radius: 4\n                    antialiasing: true\n                    visible: {active_expr}\n                    color: chrome.accent\n""",
        f"""                Item {{\n                    id: {status_id}\n                    width: 7\n                    height: 18\n                    visible: {active_expr}\n\n                    Rectangle {{\n                        anchors.centerIn: parent\n                        width: 7\n                        height: 7\n                        radius: 4\n                        antialiasing: true\n                        color: chrome.accent\n""",
        "status dot",
    )

    text = path.read_text(encoding="utf-8")
    marker = f"id: {status_id}"
    pos = text.index(marker)
    prefix, tail = text[:pos], text[pos:]
    old_close = """                    }\n                }\n\n                Text {\n"""
    new_close = """                    }\n                    }\n                }\n\n                Text {\n"""
    if old_close not in tail:
        raise SystemExit(f"{path}: status lane close not found")
    tail = tail.replace(old_close, new_close, 1)
    path.write_text(prefix + tail, encoding="utf-8")

    replace_once(
        path,
        f"""                Text {{\n                    text: {active_expr} ? \"{active_text}\" : \"{idle_text}\"\n""",
        f"""                Text {{\n                    height: 18\n                    verticalAlignment: Text.AlignVCenter\n                    text: {active_expr} ? \"{active_text}\" : \"{idle_text}\"\n""",
        "status label",
    )


polish(
    link / "BluetoothMain.qml",
    "discoveryStatusLane",
    "root.bluetooth.discovering",
    "Looking…",
    "Find Devices",
)
polish(
    link / "MahoLinkMain.qml",
    "scanStatusLane",
    "root.wifi.busy",
    "Scanning…",
    "Refresh",
)

print("Maho Link connectivity indicator polish applied.")
