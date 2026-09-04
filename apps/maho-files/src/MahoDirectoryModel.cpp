#include "MahoDirectoryModel.h"

#include <QDesktopServices>
#include <QDir>
#include <QLocale>
#include <QUrl>

#include <KIO/Job>

#include <algorithm>

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

void MahoDirectoryModel::navigate(const QUrl &url, bool recordHistory)
{
    if (!url.isValid() || url.isEmpty()) {
        setErrorString(QStringLiteral("That location is not valid."));
        return;
    }

    if (recordHistory) {
        if (m_historyIndex + 1 < m_history.size())
            m_history.resize(m_historyIndex + 1);

        if (m_history.isEmpty() || m_history.constLast() != url)
            m_history.append(url);

        m_historyIndex = m_history.size() - 1;
        emit historyChanged();
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

void MahoDirectoryModel::rebuildFromLister()
{
    const KFileItemList listed = m_lister.items(KCoreDirLister::FilteredItems);

    beginResetModel();
    m_items.clear();
    m_items.reserve(listed.size());
    for (const KFileItem &item : listed)
        m_items.append(item);
    sortItems();
    endResetModel();
}

void MahoDirectoryModel::sortItems()
{
    std::sort(m_items.begin(), m_items.end(), [](const KFileItem &left, const KFileItem &right) {
        if (left.isDir() != right.isDir())
            return left.isDir();
        return QString::localeAwareCompare(left.text(), right.text()) < 0;
    });
}
