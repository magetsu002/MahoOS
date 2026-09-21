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
require_text "$MODEL_CPP" 'mime->setUrls({item.url()});' \
    'drag payload does not export a standards-aware URL list'
require_text "$MODEL_CPP" 'drag.exec(Qt::CopyAction);' \
    'file/folder drag does not enter the native drag-and-drop session'
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
assert 'mime->setUrls({item.url()});' in body, 'drag source lost its URL payload'
PY_DRAG
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
require_text "$MODEL_CPP" 'KIO::copy(urls, m_currentUrl' \
    'inbound drop copy is not delegated to KIO'
require_text "$MODEL_CPP" 'KIO::move(urls, m_currentUrl' \
    'inbound drop move is not delegated to KIO'
require_text "$QML" 'DropArea {' \
    'file content does not accept native drops'
require_text "$QML" 'drop.acceptProposedAction()' \
    'drop action is not acknowledged back to the source'
echo PASS

echo 'ALL MAHO FILES DND + SEARCH CONTRACTS PASS'
