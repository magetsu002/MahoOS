#include "MahoDirectoryModel.h"

#include <QClipboard>
#include <QDesktopServices>
#include <QDir>
#include <QGuiApplication>
#include <QLocale>
#include <QMimeData>
#include <QUrl>

#include <KIO/CopyJob>
#include <KIO/Job>
#include <KIO/MkdirJob>
#include <KJob>

#include <algorithm>
#include <utility>

MahoDirectoryModel::MahoDirectoryModel(QObject *parent)
    : QAbstractListModel(parent)
    , m_lister(this)
{
    m_lister.setAutoUpdate(true);
    m_lister.setDelayedMimeTypes(false);
    m_lister.setRequestMimeTypeWhileListing(true);
    m_lister.setShowHiddenFiles(m_showHidden);

    connect(&m_lister, &KCoreDirLister::started, this, [this](const QUrl &) {
        setErrorString({});
        setLoading(true);
    });

    connect(&m_lister, &KCoreDirLister::clear, this, [this]() {
        beginResetModel();
        m_sourceItems.clear();
        m_items.clear();
        endResetModel();
    });

    connect(&m_lister, &KCoreDirLister::itemsAdded, this,
            [this](const QUrl &, const KFileItemList &) {
        rebuildFromLister();
    });

    connect(&m_lister, &KCoreDirLister::itemsDeleted, this,
            [this](const KFileItemList &) {
        rebuildFromLister();
    });

    connect(&m_lister, &KCoreDirLister::refreshItems, this,
            [this](const QList<QPair<KFileItem, KFileItem>> &) {
        rebuildFromLister();
    });

    connect(&m_lister, &KCoreDirLister::completed, this, [this]() {
        rebuildFromLister();
        setLoading(false);
    });

    connect(&m_lister, &KCoreDirLister::canceled, this, [this]() {
        setLoading(false);
    });

    connect(&m_lister, &KCoreDirLister::jobError, this, [this](KIO::Job *job) {
        setLoading(false);
        setErrorString(job ? job->errorString() : QStringLiteral("Could not read this location."));
    });

    connect(&m_lister, &KCoreDirLister::redirection, this,
            [this](const QUrl &, const QUrl &newUrl) {
        setCurrentUrl(newUrl);
        if (m_historyIndex >= 0 && m_historyIndex < m_history.size()) {
            m_history[m_historyIndex] = newUrl;
            emit historyChanged();
        }
    });

    if (QGuiApplication::clipboard()) {
        connect(QGuiApplication::clipboard(), &QClipboard::dataChanged,
                this, &MahoDirectoryModel::canPasteChanged);
    }

    navigate(QUrl::fromLocalFile(QDir::homePath()), true);
}

int MahoDirectoryModel::rowCount(const QModelIndex &parent) const
{
    return parent.isValid() ? 0 : m_items.size();
}

QVariant MahoDirectoryModel::data(const QModelIndex &index, int role) const
{
    if (!index.isValid() || index.row() < 0 || index.row() >= m_items.size())
        return {};

    const KFileItem &item = m_items.at(index.row());

    switch (role) {
    case Qt::DisplayRole:
    case NameRole:
        return item.text();
    case UrlRole:
        return item.url();
    case IconNameRole:
        return item.iconName();
    case DirectoryRole:
        return item.isDir();
    case HiddenRole:
        return item.isHidden();
    case SizeRole:
        return QVariant::fromValue<qulonglong>(item.size());
    case SizeTextRole:
        return item.isDir() ? QString() : QLocale().formattedDataSize(item.size());
    case MimeTypeRole:
        return item.mimetype();
    case MimeCommentRole:
        return item.mimeComment();
    case ModifiedRole:
        return item.time(KFileItem::ModificationTime);
    case ModifiedTextRole:
        return item.timeString(KFileItem::ModificationTime);
    case LocalRole:
        return item.url().isLocalFile();
    case PreviewUrlRole:
        if (item.url().isLocalFile() && item.mimetype().startsWith(QStringLiteral("image/")))
            return item.url();
        return QUrl();
    default:
        return {};
    }
}

QHash<int, QByteArray> MahoDirectoryModel::roleNames() const
{
    return {
        {NameRole, "name"},
        {UrlRole, "url"},
        {IconNameRole, "iconName"},
        {DirectoryRole, "isDirectory"},
        {HiddenRole, "isHidden"},
        {SizeRole, "size"},
        {SizeTextRole, "sizeText"},
        {MimeTypeRole, "mimeType"},
        {MimeCommentRole, "mimeComment"},
        {ModifiedRole, "modified"},
        {ModifiedTextRole, "modifiedText"},
        {LocalRole, "isLocal"},
        {PreviewUrlRole, "previewUrl"},
    };
}

QUrl MahoDirectoryModel::currentUrl() const
{
    return m_currentUrl;
}

QString MahoDirectoryModel::displayPath() const
{
    if (m_currentUrl.isLocalFile())
        return QDir::toNativeSeparators(m_currentUrl.toLocalFile());
    return m_currentUrl.toDisplayString(QUrl::PreferLocalFile);
}

bool MahoDirectoryModel::loading() const
{
    return m_loading;
}

QString MahoDirectoryModel::errorString() const
{
    return m_errorString;
}

bool MahoDirectoryModel::canGoBack() const
{
    return m_historyIndex > 0;
}

bool MahoDirectoryModel::canGoForward() const
{
    return m_historyIndex >= 0 && m_historyIndex + 1 < m_history.size();
}

bool MahoDirectoryModel::showHidden() const
{
    return m_showHidden;
}

QString MahoDirectoryModel::searchQuery() const
{
    return m_searchQuery;
}

bool MahoDirectoryModel::operationBusy() const
{
    return m_operationBusy;
}

QString MahoDirectoryModel::operationMessage() const
{
    return m_operationMessage;
}

bool MahoDirectoryModel::canPaste() const
{
    const QClipboard *clipboard = QGuiApplication::clipboard();
    const QMimeData *mime = clipboard ? clipboard->mimeData() : nullptr;
    return mime && !mime->urls().isEmpty();
}

void MahoDirectoryModel::openUrl(const QUrl &url)
{
    navigate(url, true);
}

void MahoDirectoryModel::openLocation(const QString &location)
{
    const QString base = m_currentUrl.isLocalFile() ? m_currentUrl.toLocalFile() : QDir::homePath();
    const QUrl url = QUrl::fromUserInput(location.trimmed(), base, QUrl::AssumeLocalFile);
    navigate(url, true);
}

void MahoDirectoryModel::openIndex(int row)
{
    if (row < 0 || row >= m_items.size())
        return;

    const KFileItem item = m_items.at(row);
    if (item.isDir()) {
        navigate(item.url(), true);
        return;
    }

    QDesktopServices::openUrl(item.url());
}

void MahoDirectoryModel::goBack()
{
    if (!canGoBack())
        return;
    --m_historyIndex;
    emit historyChanged();
    navigate(m_history.at(m_historyIndex), false);
}

void MahoDirectoryModel::goForward()
{
    if (!canGoForward())
        return;
    ++m_historyIndex;
    emit historyChanged();
    navigate(m_history.at(m_historyIndex), false);
}

void MahoDirectoryModel::goUp()
{
    if (!m_currentUrl.isValid())
        return;

    QUrl parent = m_currentUrl.adjusted(QUrl::StripTrailingSlash);
    parent = parent.adjusted(QUrl::RemoveFilename);
    if (parent.isValid() && !parent.isEmpty() && parent != m_currentUrl)
        navigate(parent, true);
}

void MahoDirectoryModel::goHome()
{
    navigate(QUrl::fromLocalFile(QDir::homePath()), true);
}

void MahoDirectoryModel::reload()
{
    if (!m_currentUrl.isValid())
        return;
    navigate(m_currentUrl, false);
}

void MahoDirectoryModel::setShowHidden(bool show)
{
    if (m_showHidden == show)
        return;

    m_showHidden = show;
    m_lister.setShowHiddenFiles(show);
    emit showHiddenChanged();
    reload();
}

void MahoDirectoryModel::setSearchQuery(const QString &query)
{
    const QString normalized = query.trimmed();
    if (m_searchQuery == normalized)
        return;

    m_searchQuery = normalized;
    emit searchQueryChanged();
    rebuildVisibleItems();
}

QString MahoDirectoryModel::nameAt(int row) const
{
    if (row < 0 || row >= m_items.size())
        return {};
    return m_items.at(row).text();
}

bool MahoDirectoryModel::isDirectoryAt(int row) const
{
    return row >= 0 && row < m_items.size() && m_items.at(row).isDir();
}

void MahoDirectoryModel::createFolder(const QString &name)
{
    const QString trimmed = name.trimmed();
    if (trimmed.isEmpty()) {
        setOperationMessage(QStringLiteral("Folder name cannot be empty."));
        return;
    }

    const QUrl destination = childUrl(trimmed);
    if (!destination.isValid()) {
        setOperationMessage(QStringLiteral("Could not create that folder here."));
        return;
    }

    watchJob(KIO::mkdir(destination), QStringLiteral("Folder created"));
}

void MahoDirectoryModel::renameIndex(int row, const QString &name)
{
    if (row < 0 || row >= m_items.size())
        return;

    const QString trimmed = name.trimmed();
    if (trimmed.isEmpty()) {
        setOperationMessage(QStringLiteral("Name cannot be empty."));
        return;
    }

    const KFileItem item = m_items.at(row);
    QUrl destination = item.url();
    QString path = destination.path();
    const qsizetype slash = path.lastIndexOf(QLatin1Char('/'));
    path = (slash >= 0 ? path.left(slash + 1) : QStringLiteral("/")) + trimmed;
    destination.setPath(path);

    if (destination == item.url())
        return;

    watchJob(KIO::moveAs(item.url(), destination, KIO::HideProgressInfo),
             QStringLiteral("Renamed to %1").arg(trimmed));
}

void MahoDirectoryModel::trashIndex(int row)
{
    if (row < 0 || row >= m_items.size())
        return;

    const KFileItem item = m_items.at(row);
    if (!item.url().isLocalFile()) {
        setOperationMessage(QStringLiteral("Trash is currently available for local files only."));
        return;
    }

    watchJob(KIO::trash(item.url(), KIO::HideProgressInfo),
             QStringLiteral("Moved %1 to Trash").arg(item.text()));
}

void MahoDirectoryModel::copyIndex(int row, bool cut)
{
    if (row < 0 || row >= m_items.size() || !QGuiApplication::clipboard())
        return;

    auto *mime = new QMimeData;
    mime->setUrls({m_items.at(row).url()});
    mime->setData(QStringLiteral("application/x-kde-cutselection"), cut ? QByteArrayLiteral("1") : QByteArrayLiteral("0"));
    QGuiApplication::clipboard()->setMimeData(mime);

    setOperationMessage(cut
        ? QStringLiteral("Ready to move %1").arg(m_items.at(row).text())
        : QStringLiteral("Copied %1").arg(m_items.at(row).text()));
    emit canPasteChanged();
}

void MahoDirectoryModel::paste()
{
    const QClipboard *clipboard = QGuiApplication::clipboard();
    const QMimeData *mime = clipboard ? clipboard->mimeData() : nullptr;
    if (!mime || mime->urls().isEmpty()) {
        setOperationMessage(QStringLiteral("Nothing to paste."));
        return;
    }

    if (!m_currentUrl.isValid() || m_currentUrl.isEmpty()) {
        setOperationMessage(QStringLiteral("This location cannot accept pasted files."));
        return;
    }

    const QList<QUrl> urls = mime->urls();
    const bool cut = mime->data(QStringLiteral("application/x-kde-cutselection")) == QByteArrayLiteral("1");

    KIO::CopyJob *job = cut
        ? KIO::move(urls, m_currentUrl, KIO::HideProgressInfo)
        : KIO::copy(urls, m_currentUrl, KIO::HideProgressInfo);

    watchJob(job, cut ? QStringLiteral("Moved here") : QStringLiteral("Pasted here"));
}

void MahoDirectoryModel::navigate(const QUrl &url, bool recordHistory)
{
    if (!url.isValid() || url.isEmpty()) {
        setErrorString(QStringLiteral("That location is not available."));
        return;
    }

    if (recordHistory) {
        if (m_historyIndex + 1 < m_history.size())
            m_history.resize(m_historyIndex + 1);

        if (m_history.isEmpty() || m_history.constLast() != url)
            m_history.append(url);

        m_historyIndex = m_history.size() - 1;
        emit historyChanged();

        if (!m_searchQuery.isEmpty()) {
            m_searchQuery.clear();
            emit searchQueryChanged();
        }
    }

    setCurrentUrl(url);
    setLoading(true);
    setErrorString({});
    m_lister.openUrl(url, KCoreDirLister::Reload);
}

void MahoDirectoryModel::setCurrentUrl(const QUrl &url)
{
    if (m_currentUrl == url)
        return;
    m_currentUrl = url;
    emit currentUrlChanged();
}

void MahoDirectoryModel::setLoading(bool loading)
{
    if (m_loading == loading)
        return;
    m_loading = loading;
    emit loadingChanged();
}

void MahoDirectoryModel::setErrorString(const QString &error)
{
    if (m_errorString == error)
        return;
    m_errorString = error;
    emit errorStringChanged();
}

void MahoDirectoryModel::setOperationBusy(bool busy)
{
    if (m_operationBusy == busy)
        return;
    m_operationBusy = busy;
    emit operationBusyChanged();
}

void MahoDirectoryModel::setOperationMessage(const QString &message)
{
    if (m_operationMessage == message)
        return;
    m_operationMessage = message;
    emit operationMessageChanged();
}

void MahoDirectoryModel::rebuildFromLister()
{
    const KFileItemList listed = m_lister.items(KCoreDirLister::FilteredItems);

    m_sourceItems.clear();
    m_sourceItems.reserve(listed.size());
    for (const KFileItem &item : listed)
        m_sourceItems.append(item);
    sortItems(m_sourceItems);
    rebuildVisibleItems();
}

void MahoDirectoryModel::rebuildVisibleItems()
{
    QVector<KFileItem> visible;
    visible.reserve(m_sourceItems.size());

    for (const KFileItem &item : m_sourceItems) {
        if (!m_searchQuery.isEmpty()) {
            const bool nameMatches = item.text().contains(m_searchQuery, Qt::CaseInsensitive);
            const bool typeMatches = item.mimeComment().contains(m_searchQuery, Qt::CaseInsensitive);
            if (!nameMatches && !typeMatches)
                continue;
        }
        visible.append(item);
    }

    beginResetModel();
    m_items = std::move(visible);
    endResetModel();
}

void MahoDirectoryModel::sortItems(QVector<KFileItem> &items) const
{
    std::sort(items.begin(), items.end(), [](const KFileItem &left, const KFileItem &right) {
        if (left.isDir() != right.isDir())
            return left.isDir();
        return QString::localeAwareCompare(left.text(), right.text()) < 0;
    });
}

void MahoDirectoryModel::watchJob(KJob *job, const QString &successMessage)
{
    if (!job)
        return;

    setOperationBusy(true);
    setOperationMessage({});

    connect(job, &KJob::result, this, [this, successMessage](KJob *completed) {
        setOperationBusy(false);
        if (completed->error()) {
            setOperationMessage(completed->errorString());
            return;
        }
        setOperationMessage(successMessage);
        reload();
    });
}

QUrl MahoDirectoryModel::childUrl(const QString &name) const
{
    if (!m_currentUrl.isValid() || m_currentUrl.isEmpty())
        return {};

    QUrl destination = m_currentUrl;
    QString path = destination.path();
    if (!path.endsWith(QLatin1Char('/')))
        path += QLatin1Char('/');
    path += name;
    destination.setPath(path);
    return destination;
}
