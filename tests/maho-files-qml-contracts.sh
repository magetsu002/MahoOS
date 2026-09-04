#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/apps/maho-files"
CMAKE="$APP/CMakeLists.txt"
MODEL_H="$APP/src/MahoDirectoryModel.h"
MODEL_CPP="$APP/src/MahoDirectoryModel.cpp"
PLACES_H="$APP/src/MahoPlacesController.h"
PLACES_CPP="$APP/src/MahoPlacesController.cpp"
PALETTE_H="$APP/src/MahoPalette.h"
PALETTE_CPP="$APP/src/MahoPalette.cpp"
MAIN_CPP="$APP/src/main.cpp"
QML="$APP/qml/Main.qml"
WRAPPER="$ROOT/bin/maho-files"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

require_text() {
    local file="$1"
    local text="$2"
    local message="$3"
    grep -Fq -- "$text" "$file" || fail "$message"
}

reject_text() {
    local file="$1"
    local text="$2"
    local message="$3"
    if grep -Fq -- "$text" "$file"; then
        fail "$message"
    fi
}

for file in "$CMAKE" "$MODEL_H" "$MODEL_CPP" "$PLACES_H" "$PLACES_CPP" "$PALETTE_H" "$PALETTE_CPP" "$MAIN_CPP" "$QML" "$WRAPPER"; do
    [ -f "$file" ] || fail "missing Maho Files file: $file"
done

echo "=== native backend boundary ==="
require_text "$CMAKE" 'find_package(KF6KIO CONFIG REQUIRED)' "KIO direct CMake package is not a first-class build dependency"
reject_text "$CMAKE" 'find_package(KF6 REQUIRED COMPONENTS KIO)' "Maho Files must not depend on ECM umbrella FindKF6 just to discover KIO"
require_text "$CMAKE" 'KF6::KIOCore' "directory/file semantics are not linked to KIOCore"
require_text "$CMAKE" 'KF6::KIOFileWidgets' "places/devices model is not linked to KIOFileWidgets"
require_text "$MODEL_H" '#include <KCoreDirLister>' "directory model does not use KCoreDirLister"
require_text "$MODEL_CPP" 'm_lister.openUrl' "directory navigation is not driven by KCoreDirLister"
require_text "$MAIN_CPP" 'KFilePlacesModel placesModel' "sidebar is not backed by KFilePlacesModel"
require_text "$MAIN_CPP" 'MahoPlacesController placesController' "places lifecycle is not mediated by the Maho controller"
reject_text "$MODEL_H" 'QFileSystemModel' "Maho Files reimplemented directory authority with QFileSystemModel"
reject_text "$MODEL_CPP" 'std::filesystem' "Maho Files reimplemented filesystem traversal"
reject_text "$MAIN_CPP" 'thunar' "native frontend still depends on Thunar"
reject_text "$QML" 'thunar' "visible frontend still depends on Thunar"
echo PASS

echo "=== safe device lifecycle ==="
require_text "$PLACES_CPP" 'setupNeeded(index)' "device activation does not detect required setup"
require_text "$PLACES_CPP" 'requestSetup(index)' "device activation does not request Solid/KIO setup"
require_text "$PLACES_CPP" 'KFilePlacesModel::setupDone' "device navigation does not wait for setup completion"
require_text "$PLACES_CPP" 'requestTeardown' "device unmount is not delegated to KFilePlacesModel"
require_text "$PLACES_CPP" 'requestEject' "device eject is not delegated to KFilePlacesModel"
require_text "$QML" 'placesController.activate(placeDelegate.index)' "sidebar still navigates raw device URLs"
echo PASS

echo "=== mature KIO file operations ==="
require_text "$MODEL_CPP" 'KIO::mkdir(' "new-folder operation is not delegated to KIO"
require_text "$MODEL_CPP" 'KIO::moveAs(' "rename/move operation is not delegated to KIO"
require_text "$MODEL_CPP" 'KIO::trash(' "trash operation is not delegated to KIO"
require_text "$MODEL_CPP" 'KIO::copy(' "copy/paste operation is not delegated to KIO"
require_text "$MODEL_CPP" 'application/x-kde-cutselection' "cut/paste does not interoperate with the KDE clipboard convention"
reject_text "$MODEL_CPP" 'QProcess::execute("rm"' "Maho Files must never shell out to rm for file deletion"
reject_text "$MODEL_CPP" 'std::rename' "Maho Files must not bypass KIO for rename"
reject_text "$MODEL_CPP" '::unlink(' "Maho Files must not bypass KIO for deletion"
echo PASS

echo "=== functional Maho presentation ==="
require_text "$QML" 'Qt.FramelessWindowHint' "Maho does not own the native window chrome"
require_text "$QML" 'root.startSystemMove()' "frameless window cannot use compositor-native move"
require_text "$QML" 'root.startSystemResize' "frameless window cannot use compositor-native resize"
require_text "$QML" 'model: placesModel' "native places sidebar is not rendered in QML"
require_text "$QML" 'model: directoryModel' "KIO directory items are not rendered in QML"
require_text "$QML" 'image://mahoicons/' "real themed icon artwork is not used"
require_text "$QML" 'iconName: "go-up"' "up navigation still uses an ambiguous text glyph"
require_text "$QML" 'id: morePopup' "More control is still decorative rather than functional"
require_text "$QML" 'id: contextPopup' "file context menu is missing"
require_text "$QML" 'property string viewMode: "grid"' "grid/list state is missing"
require_text "$QML" 'id: searchField' "folder search UI is missing"
require_text "$QML" 'previewUrl' "real local image previews are not rendered"
require_text "$QML" 'property color baseBackground: mahoPalette.background' "Maho palette background alias is missing"
reject_text "$QML" 'id: closeButton' "custom close control should not return to the Files toolbar"
reject_text "$QML" 'text: "×"' "custom text close glyph should not return"
reject_text "$QML" 'property color background:' "ApplicationWindow final background property must not be overridden"
reject_text "$QML" 'pointer.containsMouse' "HoverHandler must use hovered rather than containsMouse"
echo PASS

echo "=== keyboard parity ==="
for shortcut in 'Ctrl+L' 'Ctrl+F' 'Ctrl+Shift+N' 'F2' 'Delete' 'Ctrl+C' 'Ctrl+X' 'Ctrl+V'; do
    require_text "$QML" "sequence: \"$shortcut\"" "missing file-manager shortcut: $shortcut"
done
echo PASS

echo "=== Palette V2 bridge ==="
require_text "$PALETTE_CPP" 'maho/theme/active.json' "Maho Files does not consume the canonical active palette"
require_text "$PALETTE_CPP" 'surface_elevated' "semantic Palette V2 roles are not consumed"
require_text "$PALETTE_CPP" 'surface_container_high' "legacy palette compatibility is missing"
require_text "$PALETTE_H" '#include <QFileSystemWatcher>' "palette watcher dependency is not declared"
require_text "$PALETTE_H" 'QFileSystemWatcher m_watcher' "palette changes cannot be observed while the app is running"
echo PASS

echo "=== wrapper safety ==="
bash -n "$WRAPPER"
require_text "$WRAPPER" 'MAHO_FILES_BUILD_DIR' "isolated build override is missing"
require_text "$WRAPPER" 'cmake --build' "wrapper cannot build the native app"
if grep -Eq '^[[:space:]]*(sudo[[:space:]]+)?pacman[[:space:]]+-S' "$WRAPPER"; then
    fail "wrapper must never mutate packages automatically"
fi
reject_text "$WRAPPER" 'thunar --quit' "native Maho Files must not manage Thunar lifecycle"
reject_text "$WRAPPER" 'gtk-3.0' "native Maho Files must not mutate GTK configuration"
echo PASS

echo "ALL MAHO FILES QML CONTRACTS PASS"
