#include "MahoDirectoryModel.h"

#include <QClipboard>
#include <QDateTime>
#include <KIO/ApplicationLauncherJob>
#include <KIO/JobUiDelegateFactory>
#include <KIO/OpenUrlJob>
#include <KJobUiDelegate>
#include <QDir>
#include <QDrag>
#include <QFileInfo>
#include <QGuiApplication>
#include <QLocale>
#include <QMimeData>
#include <QMouseEvent>
#include <QQuickItem>
#include <QQuickWindow>
#include <QStyleHints>
#include <QUrl>

#include <KIO/CopyJob>
#include <KIO/Global>
#include <KIO/Job>
#include <KIO/ListJob>
#include <KIO/MkdirJob>
#include <KJob>

#include <algorithm>
#include <cmath>
#include <utility>

namespace {
constexpr int kMaximumSearchResults = 2000;
}

MahoDirectoryModel::MahoDirectoryModel(QObject *parent)
    : QAbstractListModel(parent)
    , m_lister(this)
{
    m_lister.setAutoUpdate(true);
    m_lister.setDelayedMimeTypes(false);
    m_lister.setRequestMimeTypeWhileListing(true);
    m_lister.setShowHiddenFiles(m_showHidden);

    m_searchDebounce.setSingleShot(true);
    m_searchDebounce.setInterval(180);
    connect(&m_searchDebounce, &QTimer::timeout, this, &MahoDirectoryModel::startSearchJob);

    connect(&m_lister, &KCoreDirLister::started, this, [this](const QUrl &) {
        if (m_searchQuery.isEmpty()) {
            setErrorString({});
            setLoading(true);
        }
    });

    connect(&m_lister, &KCoreDirLister::clear, this, [this]() {
        m_sourceItems.clear();
        if (!m_searchQuery.isEmpty())
            return;
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
        if (m_searchQuery.isEmpty())
            setLoading(false);
    });

    connect(&m_lister, &KCoreDirLister::canceled, this, [this]() {
        if (!m_recentJob && !m_searchJob)
            setLoading(false);
    });

    connect(&m_lister, &KCoreDirLister::jobError, this, [this](KIO::Job *job) {
        if (!m_searchQuery.isEmpty())
            return;
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

    if (QGuiApplication::instance())
        QGuiApplication::instance()->installEventFilter(this);

    navigate(QUrl::fromLocalFile(QDir::homePath()), true);
}

MahoDirectoryModel::~MahoDirectoryModel()
{
    // KCoreDirLister emits clear() from its destructor. Because m_lister is
    // declared before the item arrays, C++ destroys those arrays first unless
    // callbacks are severed while every member is still alive. The old order
    // let the clear lambda access freed QList storage during normal shutdown.
    disconnect(&m_lister, nullptr, this, nullptr);
    cancelRecentJob();
    cancelSearchJob();
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
        return searchDisplayName(item);
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
    if (m_currentUrl.scheme() == QStringLiteral("timeline")) {
        const QString tail = m_currentUrl.path().section(
            QLatin1Char('/'), -1, -1, QString::SectionSkipEmpty);
        if (tail == QStringLiteral("recent"))
            return QStringLiteral("Recent Files");

        const QDate date = timelineDate(m_currentUrl);
        if (date == QDate::currentDate())
            return QStringLiteral("Modified Today");
        if (date == QDate::currentDate().addDays(-1))
            return QStringLiteral("Modified Yesterday");
        if (date.isValid())
            return QStringLiteral("Modified %1").arg(QLocale().toString(date, QLocale::ShortFormat));
        return QStringLiteral("Recent Files");
    }

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
    if (!m_currentUrl.isLocalFile())
        return false;

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

    auto *job = new KIO::OpenUrlJob(item.url(), item.mimetype(), this);
    job->setUiDelegate(KIO::createDefaultJobUiDelegate(
        KJobUiDelegate::AutoHandlingEnabled, nullptr));
    connect(job, &KJob::result, this, [this, item](KJob *completed) {
        if (completed->error()) {
            setOperationMessage(QStringLiteral("Could not open %1: %2")
                .arg(item.text(), completed->errorString()));
        }
    });
    job->start();
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

    if (m_currentUrl.scheme() == QStringLiteral("timeline")) {
        goHome();
        return;
    }

    QUrl parent = m_currentUrl.adjusted(QUrl::StripTrailingSlash);
    parent = parent.adjusted(QUrl::RemoveFilename);
    if (parent.isValid() && !parent.isEmpty() && parent != m_currentUrl)
        navigate(parent, true);
}

void MahoDirectoryModel::goHome()
{
    navigate(QUrl::fromLocalFile(QDir::homePath()), true);
}

void MahoDirectoryModel::goRecent()
{
    navigate(QUrl(QStringLiteral("timeline:/recent")), true);
}

void MahoDirectoryModel::reload()
{
    if (!m_currentUrl.isValid())
        return;

    if (!m_searchQuery.isEmpty() && m_currentUrl.isLocalFile()) {
        m_searchDebounce.stop();
        startSearchJob();
        return;
    }

    navigate(m_currentUrl, false);
}

void MahoDirectoryModel::setShowHidden(bool show)
{
    if (m_showHidden == show)
        return;

    m_showHidden = show;
    m_lister.setShowHiddenFiles(show);
    emit showHiddenChanged();

    if (!m_searchQuery.isEmpty() && m_currentUrl.isLocalFile()) {
        m_searchDebounce.start();
        return;
    }

    reload();
}

void MahoDirectoryModel::setSearchQuery(const QString &query)
{
    const QString normalized = query.trimmed();
    if (m_searchQuery == normalized)
        return;

    cancelSearchJob();
    m_searchDebounce.stop();
    m_searchQuery = normalized;
    emit searchQueryChanged();

    if (m_searchQuery.isEmpty()) {
        m_searchItems.clear();
        setLoading(false);
        setErrorString({});
        setOperationMessage({});
        rebuildVisibleItems();
        return;
    }

    if (!m_currentUrl.isLocalFile()) {
        rebuildVisibleItems();
        return;
    }

    beginResetModel();
    m_items.clear();
    endResetModel();

    setLoading(true);
    setErrorString({});
    setOperationMessage(QStringLiteral("Searching %1 and subfolders…").arg(displayPath()));
    m_searchDebounce.start();
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
        setOperationMessage(QStringLiteral("Create a folder from a writable local location."));
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
    trashRows(QVariantList { row });
}

void MahoDirectoryModel::trashRows(const QVariantList &rows)
{
    const QVector<int> normalized = normalizedRows(rows);
    if (normalized.isEmpty())
        return;

    const QList<QUrl> urls = urlsForRows(normalized);
    if (urls.size() != normalized.size()) {
        setOperationMessage(QStringLiteral("Trash is currently available for local files only."));
        return;
    }
    for (const QUrl &url : urls) {
        if (!url.isLocalFile()) {
            setOperationMessage(QStringLiteral("Trash is currently available for local files only."));
            return;
        }
    }

    const QString success = normalized.size() == 1
        ? QStringLiteral("Moved %1 to Trash").arg(m_items.at(normalized.first()).text())
        : QStringLiteral("Moved %1 items to Trash").arg(normalized.size());
    watchJob(KIO::trash(urls, KIO::HideProgressInfo), success);
}

void MahoDirectoryModel::copyIndex(int row, bool cut)
{
    copyRows(QVariantList { row }, cut);
}

void MahoDirectoryModel::copyRows(const QVariantList &rows, bool cut)
{
    if (!QGuiApplication::clipboard())
        return;

    const QVector<int> normalized = normalizedRows(rows);
    const QList<QUrl> urls = urlsForRows(normalized);
    if (urls.isEmpty())
        return;

    auto *mime = new QMimeData;
    mime->setUrls(urls);
    mime->setData(QStringLiteral("application/x-kde-cutselection"), cut ? QByteArrayLiteral("1") : QByteArrayLiteral("0"));
    QGuiApplication::clipboard()->setMimeData(mime);

    if (normalized.size() == 1) {
        setOperationMessage(cut
            ? QStringLiteral("Ready to move %1").arg(m_items.at(normalized.first()).text())
            : QStringLiteral("Copied %1").arg(m_items.at(normalized.first()).text()));
    } else {
        setOperationMessage(cut
            ? QStringLiteral("Ready to move %1 items").arg(normalized.size())
            : QStringLiteral("Copied %1 items").arg(normalized.size()));
    }
    emit canPasteChanged();
}

void MahoDirectoryModel::setSelectedRows(const QVariantList &rows)
{
    m_selectedRows = normalizedRows(rows);
}

void MahoDirectoryModel::copyPathIndex(int row)
{
    if (row < 0 || row >= m_items.size() || !QGuiApplication::clipboard())
        return;

    const QUrl url = m_items.at(row).url();
    const QString value = url.isLocalFile()
        ? QDir::toNativeSeparators(url.toLocalFile())
        : url.toDisplayString(QUrl::PreferLocalFile);
    QGuiApplication::clipboard()->setText(value);
    setOperationMessage(QStringLiteral("Path copied"));
}

void MahoDirectoryModel::duplicateIndex(int row)
{
    if (row < 0 || row >= m_items.size())
        return;

    const KFileItem item = m_items.at(row);
    if (!m_currentUrl.isLocalFile() || !item.url().isLocalFile()) {
        setOperationMessage(QStringLiteral("Duplicate is available for local files and folders only."));
        return;
    }

    QFileInfo info(item.url().toLocalFile());
    QString base = item.isDir() ? info.fileName() : info.completeBaseName();
    QString suffix = item.isDir() ? QString() : info.completeSuffix();
    if (base.isEmpty())
        base = item.text();

    QDir destinationDir(m_currentUrl.toLocalFile());
    QString candidate;
    int copyNumber = 1;
    do {
        const QString tag = copyNumber == 1
            ? QStringLiteral(" copy")
            : QStringLiteral(" copy %1").arg(copyNumber);
        candidate = suffix.isEmpty()
            ? base + tag
            : base + tag + QLatin1Char('.') + suffix;
        ++copyNumber;
    } while (destinationDir.exists(candidate));

    const QUrl destination = childUrl(candidate);
    watchJob(KIO::copyAs(item.url(), destination, KIO::HideProgressInfo),
             QStringLiteral("Duplicated %1").arg(item.text()));
}

void MahoDirectoryModel::openWithIndex(int row)
{
    if (row < 0 || row >= m_items.size())
        return;

    auto *job = new KIO::ApplicationLauncherJob(this);
    job->setUrls({m_items.at(row).url()});
    job->setUiDelegate(KIO::createDefaultJobUiDelegate(
        KJobUiDelegate::AutoHandlingEnabled, nullptr));
    connect(job, &KJob::result, this, [this](KJob *completed) {
        if (completed->error())
            setOperationMessage(completed->errorString());
    });
    job->start();
}

QString MahoDirectoryModel::propertiesText(int row) const
{
    if (row < 0 || row >= m_items.size())
        return {};

    const KFileItem item = m_items.at(row);
    QStringList lines;
    lines << QStringLiteral("Name: %1").arg(item.text());
    lines << QStringLiteral("Type: %1").arg(item.mimeComment());
    if (!item.isDir())
        lines << QStringLiteral("Size: %1").arg(KIO::convertSize(item.size()));
    lines << QStringLiteral("Modified: %1").arg(
        QLocale().toString(item.time(KFileItem::ModificationTime), QLocale::LongFormat));
    lines << QStringLiteral("Location: %1").arg(
        item.url().isLocalFile()
            ? QDir::toNativeSeparators(item.url().toLocalFile())
            : item.url().toDisplayString(QUrl::PreferLocalFile));
    return lines.join(QLatin1Char('\n'));
}

void MahoDirectoryModel::dropUrls(const QVariantList &values, bool move)
{
    if (!m_currentUrl.isLocalFile()) {
        setOperationMessage(QStringLiteral("Drop files into a writable local folder."));
        return;
    }

    QList<QUrl> urls;
    urls.reserve(values.size());
    for (const QVariant &value : values) {
        const QUrl url = value.toUrl();
        if (url.isValid() && !url.isEmpty())
            urls.append(url);
    }

    if (urls.isEmpty()) {
        setOperationMessage(QStringLiteral("The drop did not contain files."));
        return;
    }

    KIO::CopyJob *job = move
        ? KIO::move(urls, m_currentUrl, KIO::HideProgressInfo)
        : KIO::copy(urls, m_currentUrl, KIO::HideProgressInfo);
    watchJob(job, move ? QStringLiteral("Moved here") : QStringLiteral("Copied here"));
}

void MahoDirectoryModel::paste()
{
    const QClipboard *clipboard = QGuiApplication::clipboard();
    const QMimeData *mime = clipboard ? clipboard->mimeData() : nullptr;
    if (!mime || mime->urls().isEmpty()) {
        setOperationMessage(QStringLiteral("Nothing to paste."));
        return;
    }

    if (!m_currentUrl.isLocalFile()) {
        setOperationMessage(QStringLiteral("Paste is available from a writable local folder."));
        return;
    }

    const QList<QUrl> urls = mime->urls();
    const bool cut = mime->data(QStringLiteral("application/x-kde-cutselection")) == QByteArrayLiteral("1");

    KIO::CopyJob *job = cut
        ? KIO::move(urls, m_currentUrl, KIO::HideProgressInfo)
        : KIO::copy(urls, m_currentUrl, KIO::HideProgressInfo);

    watchJob(job, cut ? QStringLiteral("Moved here") : QStringLiteral("Pasted here"));
}

bool MahoDirectoryModel::eventFilter(QObject *watched, QEvent *event)
{
    auto *window = qobject_cast<QQuickWindow *>(watched);
    if (!window)
        return QAbstractListModel::eventFilter(watched, event);

    switch (event->type()) {
    case QEvent::MouseButtonPress: {
        auto *mouse = static_cast<QMouseEvent *>(event);
        if (mouse->button() != Qt::LeftButton)
            break;
        m_dragCandidateRow = fileRowAt(window, mouse->position());
        m_dragStartPosition = mouse->position();
        break;
    }
    case QEvent::MouseMove: {
        auto *mouse = static_cast<QMouseEvent *>(event);
        if (m_dragCandidateRow < 0 || !(mouse->buttons() & Qt::LeftButton))
            break;

        const int threshold = QGuiApplication::styleHints()->startDragDistance();
        const QPointF delta = mouse->position() - m_dragStartPosition;
        if (std::abs(delta.x()) + std::abs(delta.y()) < threshold)
            break;

        const int row = m_dragCandidateRow;
        m_dragCandidateRow = -1;
        startDragForRow(row);
        break;
    }
    case QEvent::MouseButtonRelease:
    case QEvent::Leave:
        m_dragCandidateRow = -1;
        break;
    default:
        break;
    }

    return QAbstractListModel::eventFilter(watched, event);
}

void MahoDirectoryModel::navigate(const QUrl &url, bool recordHistory)
{
    if (!url.isValid() || url.isEmpty()) {
        setErrorString(QStringLiteral("That location is not available."));
        return;
    }

    if (url.scheme() == QStringLiteral("timeline")) {
        navigateTimeline(url, recordHistory);
        return;
    }

    cancelRecentJob();
    cancelSearchJob();
    recordNavigation(url, recordHistory);
    setCurrentUrl(url);
    setLoading(true);
    setErrorString({});
    m_lister.openUrl(url, KCoreDirLister::Reload);
}

void MahoDirectoryModel::navigateTimeline(const QUrl &url, bool recordHistory)
{
    const QString recentTail = url.path().section(
        QLatin1Char('/'), -1, -1, QString::SectionSkipEmpty);
    const bool rollingRecent = recentTail == QStringLiteral("recent");
    const QDate targetDate = timelineDate(url);
    if (!rollingRecent && !targetDate.isValid()) {
        setErrorString(QStringLiteral("This recent-files view is not valid."));
        return;
    }

    cancelSearchJob();
    cancelRecentJob();
    m_lister.stop();
    recordNavigation(url, recordHistory);
    setCurrentUrl(url);
    setErrorString({});
    setLoading(true);

    beginResetModel();
    m_sourceItems.clear();
    m_items.clear();
    endResetModel();

    m_recentTargetDate = targetDate;
    m_recentRolling = rollingRecent;
    const auto listFlags = m_showHidden
        ? KIO::ListJob::ListFlag::IncludeHidden
        : KIO::ListJob::ListFlag::ExcludeHidden;

    KIO::ListJob *job = KIO::listRecursive(
        QUrl::fromLocalFile(QDir::homePath()),
        KIO::HideProgressInfo,
        listFlags);
    job->setUiDelegate(nullptr);
    m_recentJob = job;

    connect(job, &KIO::ListJob::entries, this,
            [this, job](KIO::Job *sourceJob, const KIO::UDSEntryList &entries) {
        if (m_recentJob != job)
            return;

        auto *listJob = static_cast<KIO::ListJob *>(sourceJob);
        bool changed = false;
        for (const KIO::UDSEntry &entry : entries) {
            if (m_sourceItems.size() >= 500)
                break;

            KFileItem item(entry, listJob->url(), false, true);
            if (item.isNull() || item.text() == QStringLiteral(".") || item.text() == QStringLiteral(".."))
                continue;
            if (item.isDir())
                continue;

            const QDate modified = item.time(KFileItem::ModificationTime).date();
            if (m_recentRolling) {
                const QDate oldest = QDate::currentDate().addDays(-6);
                if (!modified.isValid() || modified < oldest || modified > QDate::currentDate())
                    continue;
            } else if (modified != m_recentTargetDate) {
                continue;
            }

            m_sourceItems.append(item);
            changed = true;
        }

        if (changed) {
            sortRecentItems(m_sourceItems);
            rebuildVisibleItems();
        }
    });

    connect(job, &KJob::result, this, [this, job](KJob *completed) {
        if (m_recentJob != job)
            return;

        m_recentJob.clear();
        if (completed->error())
            setErrorString(completed->errorString());
        sortRecentItems(m_sourceItems);
        rebuildVisibleItems();
        setLoading(false);
    });
}

void MahoDirectoryModel::recordNavigation(const QUrl &url, bool recordHistory)
{
    if (!recordHistory)
        return;

    if (m_historyIndex + 1 < m_history.size())
        m_history.resize(m_historyIndex + 1);

    if (m_history.isEmpty() || m_history.constLast() != url)
        m_history.append(url);

    m_historyIndex = m_history.size() - 1;
    emit historyChanged();

    if (!m_searchQuery.isEmpty()) {
        m_searchDebounce.stop();
        cancelSearchJob();
        m_searchQuery.clear();
        m_searchItems.clear();
        setOperationMessage({});
        emit searchQueryChanged();
    }
}

void MahoDirectoryModel::cancelRecentJob()
{
    if (!m_recentJob)
        return;

    KIO::ListJob *job = m_recentJob.data();
    m_recentJob.clear();
    job->kill();
}

void MahoDirectoryModel::cancelSearchJob()
{
    if (!m_searchJob)
        return;

    KIO::ListJob *job = m_searchJob.data();
    m_searchJob.clear();
    job->kill();
}

void MahoDirectoryModel::startSearchJob()
{
    cancelSearchJob();

    if (m_searchQuery.isEmpty() || !m_currentUrl.isLocalFile()) {
        rebuildVisibleItems();
        return;
    }

    m_searchRootUrl = m_currentUrl;
    m_searchItems.clear();

    beginResetModel();
    m_items.clear();
    endResetModel();

    setLoading(true);
    setErrorString({});
    setOperationMessage(QStringLiteral("Searching %1 and subfolders…").arg(displayPath()));

    const QString query = m_searchQuery;
    const QUrl rootUrl = m_searchRootUrl;
    const auto listFlags = m_showHidden
        ? KIO::ListJob::ListFlag::IncludeHidden
        : KIO::ListJob::ListFlag::ExcludeHidden;

    KIO::ListJob *job = KIO::listRecursive(rootUrl, KIO::HideProgressInfo, listFlags);
    job->setUiDelegate(nullptr);
    m_searchJob = job;

    connect(job, &KIO::ListJob::entries, this,
            [this, job, query](KIO::Job *sourceJob, const KIO::UDSEntryList &entries) {
        if (m_searchJob != job || m_searchQuery != query)
            return;

        auto *listJob = static_cast<KIO::ListJob *>(sourceJob);
        bool changed = false;

        for (const KIO::UDSEntry &entry : entries) {
            if (m_searchItems.size() >= kMaximumSearchResults)
                break;

            KFileItem item(entry, listJob->url(), false, true);
            if (item.isNull() || item.text() == QStringLiteral(".") || item.text() == QStringLiteral(".."))
                continue;
            if (searchRank(item, query) < 0)
                continue;

            m_searchItems.append(item);
            changed = true;
        }

        if (changed) {
            sortSearchItems(m_searchItems, query);
            beginResetModel();
            m_items = m_searchItems;
            endResetModel();
        }
    });

    connect(job, &KJob::result, this, [this, job, query, rootUrl](KJob *completed) {
        if (m_searchJob != job || m_searchQuery != query || m_searchRootUrl != rootUrl)
            return;

        m_searchJob.clear();

        if (completed->error())
            setErrorString(completed->errorString());

        sortSearchItems(m_searchItems, query);
        beginResetModel();
        m_items = m_searchItems;
        endResetModel();
        setLoading(false);

        const QString scope = rootUrl.toLocalFile() == QDir::homePath()
            ? QStringLiteral("Home")
            : QDir::toNativeSeparators(rootUrl.toLocalFile());
        const QString suffix = m_searchItems.size() >= kMaximumSearchResults
            ? QStringLiteral(" (first %1)").arg(kMaximumSearchResults)
            : QString();
        setOperationMessage(QStringLiteral("%1 result%2 in %3 + subfolders%4")
            .arg(m_searchItems.size())
            .arg(m_searchItems.size() == 1 ? QString() : QStringLiteral("s"))
            .arg(scope, suffix));
    });
}

QDate MahoDirectoryModel::timelineDate(const QUrl &url) const
{
    if (url.scheme() != QStringLiteral("timeline"))
        return {};

    QString tail = url.path().section(QLatin1Char('/'), -1, -1, QString::SectionSkipEmpty);
    if (tail == QStringLiteral("today"))
        return QDate::currentDate();
    if (tail == QStringLiteral("yesterday"))
        return QDate::currentDate().addDays(-1);

    return QDate::fromString(tail, Qt::ISODate);
}

void MahoDirectoryModel::setCurrentUrl(const QUrl &url)
{
    if (m_currentUrl == url)
        return;
    m_currentUrl = url;
    emit currentUrlChanged();
    emit canPasteChanged();
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

    if (m_searchQuery.isEmpty())
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

void MahoDirectoryModel::sortRecentItems(QVector<KFileItem> &items) const
{
    std::sort(items.begin(), items.end(), [](const KFileItem &left, const KFileItem &right) {
        const QDateTime leftTime = left.time(KFileItem::ModificationTime);
        const QDateTime rightTime = right.time(KFileItem::ModificationTime);
        if (leftTime != rightTime)
            return leftTime > rightTime;
        return QString::localeAwareCompare(left.text(), right.text()) < 0;
    });
}

void MahoDirectoryModel::sortSearchItems(QVector<KFileItem> &items, const QString &query) const
{
    std::stable_sort(items.begin(), items.end(), [this, &query](const KFileItem &left, const KFileItem &right) {
        const int leftRank = searchRank(left, query);
        const int rightRank = searchRank(right, query);
        if (leftRank != rightRank)
            return leftRank < rightRank;

        const QString leftPath = left.url().toDisplayString(QUrl::PreferLocalFile);
        const QString rightPath = right.url().toDisplayString(QUrl::PreferLocalFile);
        if (leftPath.size() != rightPath.size())
            return leftPath.size() < rightPath.size();

        return QString::localeAwareCompare(left.text(), right.text()) < 0;
    });
}

int MahoDirectoryModel::searchRank(const KFileItem &item, const QString &query) const
{
    const QString needle = query.trimmed().toCaseFolded();
    if (needle.isEmpty())
        return 0;

    const QString name = item.text().toCaseFolded();
    if (name == needle)
        return 0;
    if (name.startsWith(needle))
        return 10;
    if (name.contains(needle))
        return 20;

    const QString localPath = item.url().isLocalFile()
        ? item.url().toLocalFile().toCaseFolded()
        : item.url().toDisplayString(QUrl::PreferLocalFile).toCaseFolded();
    if (localPath.contains(needle))
        return 40;

    if (item.mimeComment().toCaseFolded().contains(needle))
        return 60;
    if (item.mimetype().toCaseFolded().contains(needle))
        return 70;

    return -1;
}

QString MahoDirectoryModel::searchDisplayName(const KFileItem &item) const
{
    if (m_searchQuery.isEmpty() || !m_searchRootUrl.isLocalFile() || !item.url().isLocalFile())
        return item.text();

    const QString rootPath = QDir::cleanPath(m_searchRootUrl.toLocalFile());
    const QString parentPath = QFileInfo(item.url().toLocalFile()).absolutePath();
    QString relativeParent = QDir(rootPath).relativeFilePath(parentPath);

    if (relativeParent.isEmpty() || relativeParent == QStringLiteral("."))
        return item.text();

    if (relativeParent.startsWith(QStringLiteral("../")))
        relativeParent = QDir::toNativeSeparators(parentPath);
    else
        relativeParent = QDir::toNativeSeparators(relativeParent);

    return QStringLiteral("%1  —  %2").arg(item.text(), relativeParent);
}

QVector<int> MahoDirectoryModel::normalizedRows(const QVariantList &rows) const
{
    QVector<int> normalized;
    normalized.reserve(rows.size());
    for (const QVariant &value : rows) {
        bool ok = false;
        const int row = value.toInt(&ok);
        if (!ok || row < 0 || row >= m_items.size())
            continue;
        if (!normalized.contains(row))
            normalized.append(row);
    }
    std::sort(normalized.begin(), normalized.end());
    return normalized;
}

QList<QUrl> MahoDirectoryModel::urlsForRows(const QVector<int> &rows) const
{
    QList<QUrl> urls;
    urls.reserve(rows.size());
    for (const int row : rows) {
        if (row < 0 || row >= m_items.size())
            continue;
        const QUrl url = m_items.at(row).url();
        if (url.isValid() && !url.isEmpty())
            urls.append(url);
    }
    return urls;
}

void MahoDirectoryModel::startDragForRow(int row)
{
    if (row < 0 || row >= m_items.size())
        return;

    QVector<int> rows { row };
    if (m_selectedRows.size() > 1 && m_selectedRows.contains(row))
        rows = m_selectedRows;

    const QList<QUrl> urls = urlsForRows(rows);
    if (urls.isEmpty())
        return;

    auto *mime = new QMimeData;
    mime->setUrls(urls);
    QStringList displayUrls;
    displayUrls.reserve(urls.size());
    for (const QUrl &url : urls)
        displayUrls.append(url.toDisplayString(QUrl::PreferLocalFile));
    mime->setText(displayUrls.join(QLatin1Char('\n')));

    QDrag drag(this);
    drag.setMimeData(mime);
    drag.exec(Qt::CopyAction);
}

int MahoDirectoryModel::fileRowAt(QQuickWindow *window, const QPointF &scenePosition) const
{
    if (!window || !window->contentItem())
        return -1;

    // The content DropArea intentionally sits above the delegates so inbound
    // drops remain reliable. A normal childAt() hit therefore sees that overlay
    // first and can never discover the file underneath it. Walk every visible
    // visual branch under the pointer and look only for the explicit file-row
    // marker instead of treating the topmost overlay as authoritative.
    return fileRowAtItem(window->contentItem(), scenePosition);
}

int MahoDirectoryModel::fileRowAtItem(QQuickItem *root, const QPointF &scenePosition) const
{
    if (!root || !root->isVisible() || root->opacity() <= 0.0)
        return -1;

    const QPointF local = root->mapFromScene(scenePosition);
    if (!root->contains(local))
        return -1;

    auto children = root->childItems();
    std::stable_sort(children.begin(), children.end(), [](QQuickItem *left, QQuickItem *right) {
        return left->z() > right->z();
    });
    for (QQuickItem *child : children) {
        const int row = fileRowAtItem(child, scenePosition);
        if (row >= 0)
            return row;
    }

    const QVariant rowValue = root->property("mahoFileRow");
    if (!rowValue.isValid())
        return -1;

    bool ok = false;
    const int row = rowValue.toInt(&ok);
    return ok && row >= 0 && row < m_items.size() ? row : -1;
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
    if (!m_currentUrl.isLocalFile())
        return {};

    QUrl destination = m_currentUrl;
    QString path = destination.path();
    if (!path.endsWith(QLatin1Char('/')))
        path += QLatin1Char('/');
    path += name;
    destination.setPath(path);
    return destination;
}
