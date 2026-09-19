#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/apps/maho-files"
CMAKE="$APP/CMakeLists.txt"
DESKTOP="$APP/io.maho.Files.desktop"
MODEL_H="$APP/src/MahoDirectoryModel.h"
MODEL_CPP="$APP/src/MahoDirectoryModel.cpp"
PLACES_H="$APP/src/MahoPlacesController.h"
PLACES_CPP="$APP/src/MahoPlacesController.cpp"
PALETTE_H="$APP/src/MahoPalette.h"
PALETTE_CPP="$APP/src/MahoPalette.cpp"
MAIN_CPP="$APP/src/main.cpp"
QML="$APP/qml/Main.qml"
WRAPPER="$ROOT/bin/maho-files"
FINGERPRINT="$APP/source-fingerprint.py"
LAUNCHER_BACKEND="$ROOT/lib/maho_launcher_backend.py"

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

for file in "$CMAKE" "$DESKTOP" "$MODEL_H" "$MODEL_CPP" "$PLACES_H" "$PLACES_CPP" "$PALETTE_H" "$PALETTE_CPP" "$MAIN_CPP" "$QML" "$WRAPPER" "$LAUNCHER_BACKEND" "$FINGERPRINT"; do
    [ -f "$file" ] || fail "missing Maho Files file: $file"
done

echo "=== native backend boundary ==="
require_text "$CMAKE" 'find_package(KF6KIO CONFIG REQUIRED)' "KIO direct CMake package is not a first-class build dependency"
reject_text "$CMAKE" 'find_package(KF6 REQUIRED COMPONENTS KIO)' "Maho Files must not depend on ECM umbrella FindKF6 just to discover KIO"
require_text "$CMAKE" 'Qt6::Widgets' "KIO FileWidgets are used without the Qt Widgets runtime"
require_text "$CMAKE" 'KF6::KIOCore' "directory/file semantics are not linked to KIOCore"
require_text "$CMAKE" 'KF6::KIOFileWidgets' "places/devices model is not linked to KIOFileWidgets"
require_text "$MAIN_CPP" 'QApplication application(argc, argv)' "KIO FileWidgets must run under QApplication, not QGuiApplication"
reject_text "$MAIN_CPP" 'QGuiApplication application(argc, argv)' "QGuiApplication reintroduces the device QWidget crash"
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

echo "=== recent views without optional timeline worker ==="
require_text "$MODEL_CPP" 'url.scheme() == QStringLiteral("timeline")' "timeline places are still handed to an optional KIO worker"
require_text "$MODEL_CPP" 'KIO::listRecursive(' "Recent views are not built asynchronously through KIOCore"
require_text "$MODEL_CPP" 'QUrl::fromLocalFile(QDir::homePath())' "Recent view does not use Home as its bounded source"
require_text "$MODEL_CPP" 'modified != m_recentTargetDate' "exact-date Recent view is not filtered by the requested modification date"
require_text "$MODEL_CPP" 'QDate::currentDate().addDays(-6)' "rolling Recent is not bounded to the last seven days"
require_text "$MODEL_CPP" 'job->setUiDelegate(nullptr)' "Recent scan may spawn an unrelated widgets progress UI"
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
require_text "$QML" 'image://mahoicons/' "real themed file/place artwork is not used"
require_text "$QML" 'component ToolbarGlyph: Canvas' "critical toolbar artwork is still delegated to theme-dependent icons"
for glyph in 'glyph: "back"' 'glyph: "forward"' 'glyph: "up"' 'glyph: "home"' 'glyph: "search"' 'glyph: "more"'; do
    require_text "$QML" "$glyph" "missing Maho-owned toolbar glyph: $glyph"
done
reject_text "$QML" 'iconName: "go-home"' "Home toolbar returned to theme/emoji artwork"
require_text "$QML" 'id: morePopup' "More control is still decorative rather than functional"
require_text "$QML" 'id: contextPopup' "file context menu is missing"
require_text "$QML" 'property string viewMode: "grid"' "grid/list state is missing"
require_text "$QML" 'id: searchField' "folder search UI is missing"
require_text "$QML" 'previewUrl' "real local image previews are not rendered"
require_text "$QML" 'property color baseBackground: mahoPalette.background' "Maho palette background alias is missing"
require_text "$QML" 'property real sidebarWidth: 228' "sidebar does not expose user-resizable width state"
require_text "$QML" 'id: sidebarSplitter' "sidebar resize splitter is missing"
require_text "$QML" 'Qt.SizeHorCursor' "sidebar splitter does not advertise horizontal resize"
require_text "$QML" 'Math.max(180, Math.min(420' "sidebar resize is not bounded to a usable range"
reject_text "$QML" 'id: closeButton' "custom close control should not return to the Files toolbar"
reject_text "$QML" 'text: "×"' "custom text close glyph should not return"
reject_text "$QML" 'property color background:' "ApplicationWindow final background property must not be overridden"
reject_text "$QML" 'pointer.containsMouse' "HoverHandler must use hovered rather than containsMouse"
echo PASS

echo "=== responsive native resize contract ==="
require_text "$QML" 'minimumWidth: 320' "Maho Files reintroduced an oversized minimum width"
require_text "$QML" 'minimumHeight: 240' "Maho Files reintroduced an oversized minimum height"
reject_text "$QML" 'minimumWidth: 820' "legacy wide-only minimum width returned"
reject_text "$QML" 'minimumHeight: 560' "legacy tall-only minimum height returned"
require_text "$QML" 'readonly property bool narrowWindow: width < 700' "narrow responsive breakpoint is missing"
require_text "$QML" 'visible: !root.narrowWindow' "sidebar/splitter do not collapse on narrow windows"
require_text "$QML" 'Layout.minimumWidth: 64' "toolbar path field cannot yield enough space when narrow"
require_text "$QML" 'contentArea.width >= 520' "list size column does not collapse responsively"
require_text "$QML" 'contentArea.width >= 700' "list type column does not collapse responsively"
require_text "$QML" 'contentArea.width >= 880' "list modified column does not collapse responsively"
require_text "$QML" 'component WindowResizeHandle: Item' "frameless shell does not expose reusable resize edges"
for edge in 'Qt.LeftEdge' 'Qt.RightEdge' 'Qt.TopEdge' 'Qt.BottomEdge'; do
    require_text "$QML" "edges: $edge" "missing native resize edge: $edge"
done
require_text "$QML" 'Qt.LeftEdge | Qt.TopEdge' "top-left resize corner is missing"
require_text "$QML" 'Qt.RightEdge | Qt.TopEdge' "top-right resize corner is missing"
require_text "$QML" 'Qt.LeftEdge | Qt.BottomEdge' "bottom-left resize corner is missing"
require_text "$QML" 'Qt.RightEdge | Qt.BottomEdge' "bottom-right resize corner is missing"
echo PASS

echo "=== adaptive directory scrolling ==="
require_text "$QML" 'function adaptiveScrollMultiplier(view)' "Files has no directory-depth scroll scaling"
require_text "$QML" 'Math.min(3.20, scaled)' "Files adaptive scroll has no sane upper bound"
require_text "$QML" 'Math.sqrt(multiplier)' "touchpad scrolling does not use softened acceleration"
require_text "$QML" 'id: gridWheelScroll' "grid view lacks adaptive wheel animation"
require_text "$QML" 'id: listWheelScroll' "list view lacks adaptive wheel animation"
require_text "$QML" 'blocking: true' "adaptive wheel handling can double-scroll with Flickable defaults"
require_text "$QML" 'grid.cellHeight * 0.72' "grid wheel step is not tied to visible cell geometry"
require_text "$QML" '88,' "list wheel step lost its bounded baseline"
echo PASS

echo "=== keyboard parity ==="
for shortcut in 'Ctrl+L' 'Ctrl+F' 'Ctrl+Shift+N' 'F2' 'Delete' 'Ctrl+C' 'Ctrl+X' 'Ctrl+V'; do
    require_text "$QML" "sequence: \"$shortcut\"" "missing file-manager shortcut: $shortcut"
done
echo PASS

echo "=== type-to-search ownership ==="
require_text "$QML" 'function handleBrowseKey(event)' "shared printable-key search handoff is missing"
require_text "$QML" 'Keys.onPressed: function(event) { root.handleBrowseKey(event) }' "browse surfaces do not route unhandled keys to search"
require_text "$QML" 'root.textEntryHasFocus()' "type-to-search can steal focus from an existing text field"
require_text "$QML" 'namePopup.opened' "type-to-search can interfere with rename/new-folder editing"
require_text "$QML" 'Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier' "type-to-search does not protect keyboard shortcuts"
require_text "$QML" 'searchField.text = typed' "first printable character is not inserted atomically"
require_text "$QML" 'searchField.cursorPosition = searchField.text.length' "search cursor is not placed after the handed-off character"
require_text "$QML" 'function closeSearch()' "Escape search cleanup is not shared"
echo PASS

echo "=== canonical desktop identity ==="
require_text "$MAIN_CPP" 'setDesktopFileName(QStringLiteral("io.maho.Files"))' "Wayland desktop identity drifted from io.maho.Files"
require_text "$DESKTOP" 'Name=Maho Files' "desktop entry is not branded as Maho Files"
require_text "$DESKTOP" 'Exec=maho-files %U' "standalone desktop entry does not launch the native binary directly"
require_text "$DESKTOP" 'MimeType=inode/directory;' "desktop entry does not advertise directory capability"
require_text "$CMAKE" 'io.maho.Files.desktop' "desktop identity is not installed with the native app"
require_text "$CMAKE" '${CMAKE_INSTALL_DATADIR}/applications' "desktop entry install target is not XDG applications"
require_text "$MODEL_H" '~MahoDirectoryModel() override' "directory model has no explicit safe shutdown"
require_text "$MODEL_CPP" 'disconnect(&m_lister, nullptr, this, nullptr)' "KIO callbacks survive into destroyed item storage"
reject_text "$WRAPPER" 'xdg-mime default' "preview/install wrapper must not silently change the user's default file manager"
echo PASS

echo "=== Launcher integration ==="
require_text "$LAUNCHER_BACKEND" 'maho_files = shutil.which("maho-files")' "Launcher does not discover Maho Files safely"
require_text "$LAUNCHER_BACKEND" 'if path.is_dir() and maho_files:' "Launcher directory results do not prefer Maho Files"
require_text "$LAUNCHER_BACKEND" 'return detached([maho_files, "run", str(path)])' "Launcher directory launch does not use bounded Maho Files CLI"
require_text "$LAUNCHER_BACKEND" 'return detached([maho_files, "run", str(Path.home())])' "Launcher Files quick action does not prefer Maho Files"
require_text "$LAUNCHER_BACKEND" 'xdg-open' "regular file opening lost standards-aware fallback"
require_text "$LAUNCHER_BACKEND" 'thunar' "legacy file-manager fallback was removed prematurely"
reject_text "$LAUNCHER_BACKEND" 'xdg-mime default' "Launcher must not mutate MIME defaults"
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
require_text "$WRAPPER" 'verified_binary' "runtime does not verify selected native artifact provenance"
require_text "$WRAPPER" 'binary_fingerprint' "runtime trusts binary existence instead of embedded identity"
require_text "$CMAKE" 'MAHO_FILES_SOURCE_FINGERPRINT' "native build does not embed source identity"
require_text "$MAIN_CPP" 'MAHO_FILES_SOURCE_FINGERPRINT=' "native executable lacks an inspectable provenance marker"
if grep -Eq '^[[:space:]]*(sudo[[:space:]]+)?pacman[[:space:]]+-S' "$WRAPPER"; then
    fail "wrapper must never mutate packages automatically"
fi
reject_text "$WRAPPER" 'thunar --quit' "native Maho Files must not manage Thunar lifecycle"
reject_text "$WRAPPER" 'gtk-3.0' "native Maho Files must not mutate GTK configuration"
echo PASS

echo "=== recent/open/action polish ==="
require_text "$MODEL_CPP" 'timeline:/recent' "rolling Recent destination is missing"
require_text "$MODEL_CPP" 'QDate::currentDate().addDays(-6)' "Recent is not bounded to a seven-day window"
require_text "$MODEL_CPP" 'KIO::OpenUrlJob' "regular file opening does not use native KIO launcher"
require_text "$MODEL_CPP" 'KIO::ApplicationLauncherJob' "Open With does not use native KDE application chooser"
require_text "$MODEL_CPP" 'copyPathIndex' "Copy Path action is missing"
require_text "$MODEL_CPP" 'duplicateIndex' "Duplicate action is missing"
require_text "$MODEL_CPP" 'propertiesText' "Properties action is missing"
require_text "$MODEL_CPP" 'dropUrls' "native inbound drop path is missing"
require_text "$QML" 'text: "Recent"' "Recent is not surfaced in the sidebar"
require_text "$QML" 'label: "Open With…"' "Open With action is not surfaced"
require_text "$QML" 'label: "Copy Path"' "Copy Path action is not surfaced"
require_text "$QML" 'label: "Duplicate"' "Duplicate action is not surfaced"
require_text "$QML" 'id: propertiesPopup' "Properties UI is missing"
require_text "$QML" 'id: contentDropArea' "content drop target is missing"
require_text "$CMAKE" 'KF6::KIOGui' "native file launching is not linked against KIOGui"
echo PASS

echo "ALL MAHO FILES QML CONTRACTS PASS"
