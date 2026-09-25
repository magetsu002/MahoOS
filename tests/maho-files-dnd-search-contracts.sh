#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
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

echo '=== native drag-out contract ==='
require_text "$MODEL_H" 'bool eventFilter(QObject *watched, QEvent *event) override;' \
    'file drag initiation is not integrated with the native Qt event path'
require_text "$MODEL_CPP" '#include <QDrag>' \
    'native Qt drag object is missing'
require_text "$MODEL_CPP" 'mime->setUrls(urls);' \
    'drag payload does not export a standards-aware URL list'
require_text "$MODEL_CPP" 'm_selectedRows.size() > 1 && m_selectedRows.contains(row)' \
    'dragging a selected file does not carry the full current selection'
require_text "$MODEL_CPP" 'drag.exec(Qt::CopyAction | Qt::MoveAction, naturalDragAction(urls));'     'file/folder drag must expose native copy and move semantics'
reject_text "$MODEL_CPP" 'drag.exec(Qt::CopyAction);'     'native drag regressed to copy-only behavior'
require_text "$MODEL_CPP" 'fileRowAt(window, mouse->position())' \
    'drag source does not resolve the actual file delegate under the pointer'
require_text "$MODEL_CPP" 'fileRowAtItem(window->contentItem(), scenePosition)' \
    'drag hit testing still stops at the topmost content overlay'
require_text "$MODEL_CPP" 'root->property("mahoFileRow")' \
    'drag hit testing is not bound to an explicit file delegate identity'
require_text "$QML" 'property int mahoFileRow: index' \
    'file delegates do not publish native drag identity'
reject_text "$MODEL_CPP" 'deepestChildAt' \
    'topmost-only hit testing regressed and will be shadowed by the inbound DropArea'
reject_text "$MODEL_CPP" 'xdotool' \
    'drag-and-drop must not be faked through input automation'
python3 - "$MODEL_CPP" <<'PY_DRAG'
from pathlib import Path
import sys
source = Path(sys.argv[1]).read_text()
start = source.index('void MahoDirectoryModel::startDragForRow(int row)')
end = source.index('int MahoDirectoryModel::fileRowAt', start)
body = source[start:end]
assert 'item.isDir()' not in body and 'item.isFile()' not in body, \
    'drag source is type-gated; both files and folders must use the same native URL drag path'
assert 'mime->setUrls(urls);' in body, 'drag source lost its URL payload'
assert 'm_selectedRows.contains(row)' in body, 'native drag lost selected-group awareness'
PY_DRAG
echo PASS

echo '=== native multi-selection contract ==='
require_text "$MODEL_H" 'copyRows(const QVariantList &rows' \
    'bulk copy/cut API is missing'
require_text "$MODEL_H" 'trashRows(const QVariantList &rows)' \
    'bulk trash API is missing'
require_text "$MODEL_H" 'setSelectedRows(const QVariantList &rows)' \
    'native drag cannot consume the QML selection'
require_text "$MODEL_CPP" 'KIO::trash(urls, KIO::HideProgressInfo)' \
    'multi-item trash is not delegated to KIO'
require_text "$QML" 'property var selectedIndexes: []' \
    'Files has no multi-selection state'
require_text "$QML" 'function selectClicked(index, modifiers)' \
    'Ctrl/Shift item selection logic is missing'
require_text "$QML" 'sequence: "Ctrl+A"' \
    'Select All keyboard parity is missing'
require_text "$QML" 'id: rubberSelectInput' \
    'empty-space M1 drag selection input is missing'
require_text "$QML" 'id: rubberSelection' \
    'M1 drag selection has no visible marquee'
require_text "$QML" 'propagateComposedEvents: false' \
    'marquee release can leak a click into a file and collapse the persistent selection'
require_text "$QML" 'directoryModel.setSelectedRows(selectedIndexes.slice())' \
    'M1 marquee selection is not committed when the button is released'
require_text "$QML" 'selectedIndexes.length > 1 && isSelected(index)' \
    'clicking a selected group member collapses the group before native multi-drag'
require_text "$QML" 'rowsInsideSelectionRect' \
    'marquee selection does not resolve intersecting file delegates'
require_text "$QML" 'root.selectClicked(fileDelegate.index, mouse.modifiers)' \
    'grid selection does not honor keyboard modifiers'
require_text "$QML" 'root.selectClicked(listDelegate.index, mouse.modifiers)' \
    'list selection does not honor keyboard modifiers'
require_text "$QML" 'directoryModel.copyRows(root.selectedIndexes, false)' \
    'multi-selection cannot be copied as one operation'
require_text "$QML" 'directoryModel.trashRows(root.selectedIndexes)' \
    'multi-selection cannot be moved to Trash as one operation'
echo PASS

echo '=== recursive search contract ==='
require_text "$MODEL_H" 'QPointer<KIO::ListJob> m_searchJob;' \
    'recursive search does not own an explicit cancellable KIO job'
require_text "$MODEL_H" 'QTimer m_searchDebounce;' \
    'search does not debounce interactive query changes'
require_text "$MODEL_CPP" 'm_searchDebounce.setInterval(180);' \
    'search debounce contract drifted'
require_text "$MODEL_CPP" 'KIO::listRecursive(rootUrl, KIO::HideProgressInfo, listFlags)' \
    'search is still limited to the already-listed current directory'
require_text "$MODEL_CPP" 'if (name == needle)' \
    'exact filename ranking is missing'
require_text "$MODEL_CPP" 'if (name.startsWith(needle))' \
    'filename-prefix ranking is missing'
require_text "$MODEL_CPP" 'if (localPath.contains(needle))' \
    'search cannot recover files by containing path'
require_text "$MODEL_CPP" 'return QStringLiteral("%1  —  %2").arg(item.text(), relativeParent);' \
    'recursive results do not expose their containing location'
require_text "$MODEL_CPP" 'Searching %1 and subfolders…' \
    'search scope is not surfaced to the user'
require_text "$MODEL_CPP" 'result%2 in %3 + subfolders%4' \
    'completed search does not report its recursive scope'
reject_text "$MODEL_CPP" 'QDirIterator' \
    'search must stay on the KIO authority boundary rather than reimplement traversal'
reject_text "$MODEL_CPP" 'std::filesystem' \
    'search must not reimplement traversal with std::filesystem'
echo PASS

echo '=== native drag-in contract ==='
require_text "$MODEL_H" 'dropUrls(const QVariantList &values' \
    'native inbound file drop API is missing'
require_text "$MODEL_H" 'canDropUrlsTo(const QVariantList &values, const QUrl &destination)'     'drop destinations cannot be validated independently'
require_text "$MODEL_CPP" 'KIO::copy(urls, destination'     'inbound drop copy is not delegated to KIO for the real target folder'
require_text "$MODEL_CPP" 'KIO::move(urls, destination'     'inbound drop move is not delegated to KIO for the real target folder'
require_text "$QML" 'id: gridFolderDrop'     'grid folders are not native drop targets'
require_text "$QML" 'id: listFolderDrop'     'list folders are not native drop targets'
require_text "$QML" 'drop.accept(action)'     'drop action is not acknowledged back to the source'
echo PASS

echo 'ALL MAHO FILES DND + SEARCH CONTRACTS PASS'
