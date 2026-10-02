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
require_text "$MODEL_H" 'preferredDropAction('     'drop target does not own ordinary drag action selection'
require_text "$MODEL_CPP" '!internalDrag'     'external drag payloads do not default safely to copy'
require_text "$MODEL_CPP" 'sourceDevice != destinationDevice'     'cross-filesystem local drags do not default safely to copy'
require_text "$MODEL_CPP" 'Qt::ShiftModifier'     'explicit user Move selection is not preserved'
require_text "$MODEL_CPP" 'kInternalDragMimeType'     'internal native drags are not distinguished from external payloads'
reject_text "$QML" 'if ((drop.supportedActions & Qt.MoveAction) !== 0)'     'QML still infers destructive Move merely because the source supports it'
require_text "$MODEL_CPP" 'dropAction != Qt::CopyAction && dropAction != Qt::MoveAction'     'unsupported drag actions are not rejected'
require_text "$MODEL_CPP" 'sourcePath == destinationPath'     'self-drop is not rejected'
require_text "$MODEL_CPP" 'isSameOrDescendantPath(sourcePath, destinationPath)'     'folder-to-descendant recursion is not rejected by normalized ancestry'
require_text "$MODEL_CPP" 'normalizedAncestor == QStringLiteral("/")'     'filesystem-root ancestry is not handled explicitly'
require_text "$MODEL_CPP" 'rejectSameParent && sourceParent == destinationPath'     'same-directory drag no-op is not distinguished from valid paste'
require_text "$MODEL_CPP" 'validateDrop(urls, m_currentUrl, &dropError, false)'     'clipboard paste was incorrectly restricted by same-directory drag rules'
require_text "$MODEL_CPP" 'createDefaultJobUiDelegate'     'real KIO conflict/error handling is not available to file mutations'
reject_text "$MODEL_CPP" 'QMessageBox::question'     'ordinary drag moves must not gain a bespoke confirmation dialog'
echo PASS


echo '=== V1 destructive-operation distinction ==='
require_text "$MODEL_H" 'preparePermanentDelete(const QVariantList &rows)' \
    'permanent delete does not prepare stable destructive targets'
require_text "$MODEL_H" 'confirmPermanentDelete(const QString &token)' \
    'permanent delete confirmation is not token-bound'
require_text "$MODEL_CPP" '::lstat(encoded.constData(), &metadata)' \
    'permanent delete does not capture/revalidate local filesystem identity'
require_text "$MODEL_CPP" 'metadata.st_dev' \
    'permanent delete does not bind the target filesystem identity'
require_text "$MODEL_CPP" 'metadata.st_ino' \
    'permanent delete does not bind the target inode identity'
require_text "$MODEL_CPP" 'KIO::del(urls, KIO::HideProgressInfo)' \
    'permanent delete is not delegated to KIO DeleteJob'
require_text "$MODEL_CPP" 'KIO::trash(urls, KIO::HideProgressInfo)' \
    'Trash stopped using the recoverable KIO trash authority'
require_text "$QML" 'sequence: "Shift+Delete"' \
    'permanent delete has no explicit keyboard distinction'
require_text "$QML" 'id: deletePopup' \
    'permanent delete has no confirmation surface'
require_text "$QML" 'This is different from Trash and cannot be undone.' \
    'permanent delete confirmation does not explain irreversibility'
require_text "$QML" 'directoryModel.preparePermanentDelete(rows)' \
    'confirmation still stores mutable row identities instead of backend targets'
require_text "$QML" 'directoryModel.confirmPermanentDelete(confirmationToken)' \
    'confirmed permanent delete is not routed through the stable backend token'
reject_text "$QML" 'directoryModel.deleteRows(targetRows)' \
    'permanent delete regressed to resolving mutable model rows after confirmation'
echo PASS

echo '=== V1 conflict and stale-path safety ==='
require_text "$MODEL_CPP" 'An item named %1 already exists.' \
    'rename does not fail closed before an existing target'
require_text "$MODEL_CPP" 'A source item is no longer available. Reload the source folder.' \
    'stale drag/copy source is not rejected before mutation'
require_text "$MODEL_CPP" 'A selected item is no longer available. Reload this folder.' \
    'stale selected source is not rejected before destructive mutation'
require_text "$MODEL_CPP" 'createDefaultJobUiDelegate' \
    'KIO native conflict/error UI is unavailable to file operations'
reject_text "$MODEL_CPP" 'KIO::Overwrite' \
    'ordinary file operations gained silent overwrite authority'
python3 - "$MODEL_CPP" <<'PY_CONFLICTS'
from pathlib import Path
import sys
source = Path(sys.argv[1]).read_text()
for function in ('void MahoDirectoryModel::dropUrls(', 'void MahoDirectoryModel::paste()'):
    start = source.index(function)
    end = source.index('\n}', start) + 2
    body = source[start:end]
    assert 'setAutoRename(true)' not in body, f'{function} silently auto-renames conflicts'
    assert 'setAutoSkip(true)' not in body, f'{function} silently skips conflicts'
    assert 'KIO::Overwrite' not in body, f'{function} silently overwrites conflicts'
PY_CONFLICTS
echo PASS

echo '=== V1 operation progress and cancellation ==='
require_text "$MODEL_H" 'Q_PROPERTY(int operationProgress' \
    'file operations expose no progress state'
require_text "$MODEL_H" 'Q_PROPERTY(bool canCancelOperation' \
    'file operations expose no cancellation state'
require_text "$MODEL_CPP" '&KJob::percentChanged' \
    'native job progress is not observed'
require_text "$MODEL_CPP" 'job->kill(KJob::Quietly)' \
    'operation cancellation is not delegated to KJob'
require_text "$QML" 'directoryModel.operationProgress + "%"' \
    'known operation progress is not presented'
require_text "$QML" 'directoryModel.cancelOperation()' \
    'busy operation has no user cancellation action'
echo PASS

echo '=== V1 sorting and empty states ==='
require_text "$MODEL_H" 'Q_PROPERTY(QString sortKey' \
    'directory sort key is not user controllable'
require_text "$MODEL_H" 'Q_PROPERTY(bool sortDescending' \
    'directory sort direction is not user controllable'
for label in 'Sort by Name' 'Sort by Modified' 'Sort by Size' 'Sort by Type' 'Reverse Sort Order'; do
    require_text "$QML" "$label" "missing sort action: $label"
done
require_text "$QML" 'text: directoryModel.searchQuery.length > 0 ? "No results" : "This folder is empty"' \
    'empty and no-result states are not explicit'
echo PASS

echo '=== V1 richer properties ==='
require_text "$MODEL_H" 'Q_INVOKABLE void requestProperties(int row);' \
    'folder properties cannot request asynchronous metadata'
require_text "$MODEL_CPP" 'KIO::directorySize(item.url())' \
    'folder size is not computed through KIO'
require_text "$MODEL_CPP" 'KFileItem::CreationTime' \
    'creation timestamp is absent from available properties'
require_text "$MODEL_CPP" 'KFileItem::AccessTime' \
    'access timestamp is absent from available properties'
require_text "$MODEL_CPP" 'MIME: %1' \
    'properties omit MIME identity'
require_text "$QML" 'property string iconName: "unknown"' \
    'properties popup has no item artwork state'
require_text "$QML" 'directoryModel.requestProperties(row)' \
    'properties popup never requests folder metadata'
echo PASS

echo '=== V1 sidebar DnD and multi-duplicate ==='
require_text "$QML" 'id: placeDrop' \
    'valid sidebar places are not drop targets'
require_text "$QML" 'root.performDrop(drop, placeDelegate.url)' \
    'sidebar drop does not target the real place URL'
require_text "$MODEL_H" 'duplicateRows(const QVariantList &rows)' \
    'multi-selection duplicate API is missing'
require_text "$MODEL_CPP" 'job->setAutoRename(true);' \
    'multi-duplicate does not generate collision-safe sibling names'
require_text "$MODEL_CPP" 'Duplicate the selected items separately when they come from different folders.' \
    'mixed-parent search duplicates are not rejected truthfully'
require_text "$MODEL_CPP" 'QUrl::fromLocalFile(commonParent)' \
    'multi-duplicate does not target the selected items actual parent folder'
require_text "$QML" 'directoryModel.duplicateRows(root.selectedIndexes)' \
    'selected groups cannot be duplicated together'
echo PASS

echo '=== V1 external-open authority ==='
require_text "$MODEL_CPP" 'new KIO::OpenUrlJob(item.url(), item.mimetype(), this)' \
    'regular file open is not routed to the system application authority'
require_text "$MODEL_CPP" 'new KIO::ApplicationLauncherJob(this)' \
    'Open With is not routed to the KDE application authority'
reject_text "$MODEL_CPP" 'QDesktopServices::openUrl' \
    'file opening bypasses the existing KIO authority'
reject_text "$MODEL_CPP" 'xdg-open' \
    'native file opening shells out instead of using KIO'
echo PASS

echo 'ALL MAHO FILES UX CLOSURE CONTRACTS PASS'
