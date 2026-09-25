#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
MAIN="$ROOT/apps/maho-files/src/main.cpp"
QML="$ROOT/apps/maho-files/qml/Main.qml"
grep -Fq 'iconName: "document-new"' "$QML" || { echo 'FAIL New File lost document-new icon'; exit 1; }
grep -Fq 'name == QStringLiteral("document-new")' "$MAIN" || { echo 'FAIL document-new is not palette-tinted'; exit 1; }
echo 'PASS New File icon follows Maho foreground palette'
