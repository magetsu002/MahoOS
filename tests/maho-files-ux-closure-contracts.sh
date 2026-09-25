#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
MODEL_H="$ROOT/apps/maho-files/src/MahoDirectoryModel.h"
MODEL_CPP="$ROOT/apps/maho-files/src/MahoDirectoryModel.cpp"
QML="$ROOT/apps/maho-files/qml/Main.qml"

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

echo '=== blank-background context ownership ==='
require_text "$QML" 'id: backgroundPopup'     'empty directory space has no dedicated context menu'
require_text "$QML" 'acceptedButtons: Qt.LeftButton | Qt.RightButton'     'background input cannot distinguish left marquee from right-click menu'
require_text "$QML" 'if (mouse.button === Qt.RightButton)'     'secondary click is not handled separately from normal selection'
require_text "$QML" 'backgroundPopup.openAt(mouse.x, mouse.y)'     'secondary click does not open the background menu at the pointer'
require_text "$QML" 'root.beginBackgroundSelection(view, mouse.x, mouse.y, mouse.modifiers)'     'left-button marquee behavior was lost while adding the context menu'
python3 - "$QML" <<'PY'
from pathlib import Path
import sys
text=Path(sys.argv[1]).read_text()
start=text.index('    Popup {\n        id: backgroundPopup')
end=text.index('    Popup {\n        id: propertiesPopup', start)
menu=text[start:end]
for label in (
    'label: "New Folder"',
    'label: "New File"',
    'label: "Paste"',
    'Search This Folder',
    'Show Hidden Files',
    'Switch to List View',
    'label: "Reload"',
):
    assert label in menu, f'background menu missing {label}'
rubber_start=text.index('id: rubberSelectInput')
rubber_end=text.index('Rectangle {\n                        id: rubberSelection', rubber_start)
rubber=text[rubber_start:rubber_end]
assert rubber.index('rowAtContentPoint') < rubber.index('mouse.button === Qt.RightButton')
assert 'mouse.accepted = false' in rubber
assert 'beginBackgroundSelection' in rubber
PY
echo PASS

echo '=== backend-owned New File ==='
require_text "$MODEL_H" 'Q_INVOKABLE void createFile(const QString &name);'     'New File is not exposed by the native model'
require_text "$MODEL_CPP" 'KIO::storedPut(QByteArray(), destination, -1, KIO::HideProgressInfo)'     'empty regular-file creation is not delegated to KIO'
require_text "$MODEL_CPP" 'trimmed.isEmpty()'     'blank item names are not rejected'
require_text "$MODEL_CPP" 'trimmed == QStringLiteral(".") || trimmed == QStringLiteral("..")'     'dot path aliases are not rejected as item names'
require_text "$MODEL_CPP" "trimmed.contains(QLatin1Char('/'))"     'path separators are not rejected from item names'
require_text "$MODEL_CPP" '!canMutateCurrentDirectory()'     'creation is not restricted to writable local directories'
require_text "$MODEL_CPP" 'target.exists() || target.isSymLink()'     'existing targets are not rejected before empty-file creation'
require_text "$MODEL_CPP" 'm_pendingSelectionUrl = selectUrl;'     'created entries are not tracked for post-refresh selection'
require_text "$MODEL_CPP" 'emit selectRowRequested(row);'     'created entry cannot be reidentified after refresh'
require_text "$QML" 'function beginNewFile()'     'New File has no real naming flow'
require_text "$QML" 'directoryModel.createFile(nameField.text)'     'New File is QML-only state rather than a backend mutation'
echo PASS

echo '=== folder-target DnD ==='
require_text "$QML" 'id: gridFolderDrop'     'grid folder delegates are not drop destinations'
require_text "$QML" 'id: listFolderDrop'     'list folder delegates are not drop destinations'
require_text "$QML" 'root.performDrop(drop, fileDelegate.url)'     'grid drop ignores the visible folder destination'
require_text "$QML" 'root.performDrop(drop, listDelegate.url)'     'list drop ignores the visible folder destination'
require_text "$QML" 'property bool folderDropReady: false'     'folder destinations have no visible accepted-drop state'
require_text "$QML" 'property string folderDropTargetUrl: ""'     'folder target ownership is not tracked against the global content target'
require_text "$QML" 'visible: contentDropArea.containsDrag && root.folderDropTargetUrl.length === 0'     'global content feedback still shadows a real folder target'
python3 - "$QML" <<'PY'
from pathlib import Path
import re, sys
text=Path(sys.argv[1]).read_text()
grid=re.search(r'GridView \{\s*id: grid\s*z: (\d+)', text, re.S)
panel=re.search(r'Item \{\s*id: listPanel\s*z: (\d+)', text, re.S)
content=re.search(r'DropArea \{\s*id: contentDropArea.*?z: (\d+)', text, re.S)
assert grid and panel and content
assert int(content.group(1)) < int(grid.group(1))
assert int(content.group(1)) < int(panel.group(1))
PY
echo PASS

echo '=== native URL + Copy/Move semantics ==='
require_text "$MODEL_CPP" 'mime->setUrls(urls);'     'native URL MIME payload is missing'
require_text "$MODEL_CPP" 'm_selectedRows.size() > 1 && m_selectedRows.contains(row)'     'multi-selection is not carried into native drag'
require_text "$MODEL_CPP" 'drag.exec(Qt::CopyAction | Qt::MoveAction, naturalDragAction(urls));'     'drag source does not advertise both CopyAction and MoveAction'
reject_text "$MODEL_CPP" 'drag.exec(Qt::CopyAction);'     'drag source is hard-forced to copy'
require_text "$MODEL_CPP" 'KIO::move(urls, destination, KIO::HideProgressInfo)'     'MoveAction does not delegate to KIO at the chosen destination'
require_text "$MODEL_CPP" 'KIO::copy(urls, destination, KIO::HideProgressInfo)'     'CopyAction does not delegate to KIO at the chosen destination'
require_text "$MODEL_CPP" 'dropAction != Qt::CopyAction && dropAction != Qt::MoveAction'     'unsupported drag actions are not rejected'
require_text "$MODEL_CPP" 'sourcePath == destinationPath'     'self-drop is not rejected'
require_text "$MODEL_CPP" 'destinationPath.startsWith(sourcePath + QLatin1Char'     'folder-to-descendant recursion is not rejected'
require_text "$MODEL_CPP" 'rejectSameParent && sourceParent == destinationPath'     'same-directory drag no-op is not distinguished from valid paste'
require_text "$MODEL_CPP" 'validateDrop(urls, m_currentUrl, &dropError, false)'     'clipboard paste was incorrectly restricted by same-directory drag rules'
require_text "$MODEL_CPP" 'createDefaultJobUiDelegate'     'real KIO conflict/error handling is not available to file mutations'
reject_text "$MODEL_CPP" 'QMessageBox::question'     'ordinary drag moves must not gain a bespoke confirmation dialog'
echo PASS

echo 'ALL MAHO FILES UX CLOSURE CONTRACTS PASS'
