#pragma once

#include <QAbstractListModel>
#include <QDate>
#include <QEvent>
#include <QPointF>
#include <QPointer>
#include <QTimer>
#include <QUrl>
#include <QVariantList>
#include <QVector>

#include <KCoreDirLister>
#include <KFileItem>
#include <KIO/ListJob>

class KJob;
class QQuickItem;
class QQuickWindow;
namespace KIO {
class DirectorySizeJob;
}

class MahoDirectoryModel final : public QAbstractListModel
{
    Q_OBJECT
    Q_PROPERTY(QUrl currentUrl READ currentUrl NOTIFY currentUrlChanged)
    Q_PROPERTY(QString displayPath READ displayPath NOTIFY currentUrlChanged)
    Q_PROPERTY(bool loading READ loading NOTIFY loadingChanged)
    Q_PROPERTY(QString errorString READ errorString NOTIFY errorStringChanged)
    Q_PROPERTY(bool canGoBack READ canGoBack NOTIFY historyChanged)
    Q_PROPERTY(bool canGoForward READ canGoForward NOTIFY historyChanged)
    Q_PROPERTY(bool showHidden READ showHidden WRITE setShowHidden NOTIFY showHiddenChanged)
    Q_PROPERTY(QString searchQuery READ searchQuery WRITE setSearchQuery NOTIFY searchQueryChanged)
    Q_PROPERTY(QString sortKey READ sortKey WRITE setSortKey NOTIFY sortChanged)
    Q_PROPERTY(bool sortDescending READ sortDescending WRITE setSortDescending NOTIFY sortChanged)
    Q_PROPERTY(bool operationBusy READ operationBusy NOTIFY operationBusyChanged)
    Q_PROPERTY(int operationProgress READ operationProgress NOTIFY operationProgressChanged)
    Q_PROPERTY(bool canCancelOperation READ canCancelOperation NOTIFY operationBusyChanged)
    Q_PROPERTY(QString operationMessage READ operationMessage NOTIFY operationMessageChanged)
    Q_PROPERTY(bool canPaste READ canPaste NOTIFY canPasteChanged)
    Q_PROPERTY(bool canMutateCurrentDirectory READ canMutateCurrentDirectory NOTIFY currentUrlChanged)

public:
    enum Role {
        NameRole = Qt::UserRole + 1,
        UrlRole,
        IconNameRole,
        DirectoryRole,
        HiddenRole,
        SizeRole,
        SizeTextRole,
        MimeTypeRole,
        MimeCommentRole,
        ModifiedRole,
        ModifiedTextRole,
        LocalRole,
        PreviewUrlRole,
    };
    Q_ENUM(Role)

    explicit MahoDirectoryModel(QObject *parent = nullptr);
    ~MahoDirectoryModel() override;

    int rowCount(const QModelIndex &parent = QModelIndex()) const override;
    QVariant data(const QModelIndex &index, int role = Qt::DisplayRole) const override;
    QHash<int, QByteArray> roleNames() const override;

    QUrl currentUrl() const;
    QString displayPath() const;
    bool loading() const;
    QString errorString() const;
    bool canGoBack() const;
    bool canGoForward() const;
    bool showHidden() const;
    QString searchQuery() const;
    QString sortKey() const;
    bool sortDescending() const;
    bool operationBusy() const;
    int operationProgress() const;
    bool canCancelOperation() const;
    QString operationMessage() const;
    bool canPaste() const;
    bool canMutateCurrentDirectory() const;

    Q_INVOKABLE void openUrl(const QUrl &url);
    Q_INVOKABLE void openLocation(const QString &location);
    Q_INVOKABLE void openIndex(int row);
    Q_INVOKABLE void goBack();
    Q_INVOKABLE void goForward();
    Q_INVOKABLE void goUp();
    Q_INVOKABLE void goHome();
    Q_INVOKABLE void goRecent();
    Q_INVOKABLE void reload();
    Q_INVOKABLE void setShowHidden(bool show);
    Q_INVOKABLE void setSearchQuery(const QString &query);
    Q_INVOKABLE void setSortKey(const QString &key);
    Q_INVOKABLE void setSortDescending(bool descending);

    Q_INVOKABLE QString nameAt(int row) const;
    Q_INVOKABLE QString iconNameAt(int row) const;
    Q_INVOKABLE bool isDirectoryAt(int row) const;
    Q_INVOKABLE void createFolder(const QString &name);
    Q_INVOKABLE void createFile(const QString &name);
    Q_INVOKABLE void renameIndex(int row, const QString &name);
    Q_INVOKABLE void trashIndex(int row);
    Q_INVOKABLE void trashRows(const QVariantList &rows);
    Q_INVOKABLE void deleteRows(const QVariantList &rows);
    Q_INVOKABLE void copyIndex(int row, bool cut = false);
    Q_INVOKABLE void copyRows(const QVariantList &rows, bool cut = false);
    Q_INVOKABLE void setSelectedRows(const QVariantList &rows);
    Q_INVOKABLE void copyPathIndex(int row);
    Q_INVOKABLE void duplicateIndex(int row);
    Q_INVOKABLE void duplicateRows(const QVariantList &rows);
    Q_INVOKABLE void openWithIndex(int row);
    Q_INVOKABLE QString propertiesText(int row) const;
    Q_INVOKABLE void requestProperties(int row);
    Q_INVOKABLE void cancelProperties();
    Q_INVOKABLE bool canDropUrlsTo(const QVariantList &values, const QUrl &destination) const;
    Q_INVOKABLE void dropUrls(const QVariantList &values, const QUrl &destination, int action);
    Q_INVOKABLE void paste();
    Q_INVOKABLE void cancelOperation();

signals:
    void currentUrlChanged();
    void loadingChanged();
    void errorStringChanged();
    void historyChanged();
    void showHiddenChanged();
    void searchQueryChanged();
    void sortChanged();
    void operationBusyChanged();
    void operationProgressChanged();
    void operationMessageChanged();
    void canPasteChanged();
    void selectRowRequested(int row);
    void propertiesReady(const QString &details, const QString &iconName);

protected:
    bool eventFilter(QObject *watched, QEvent *event) override;

private:
    void navigate(const QUrl &url, bool recordHistory);
    void navigateTimeline(const QUrl &url, bool recordHistory);
    void recordNavigation(const QUrl &url, bool recordHistory);
    void cancelRecentJob();
    void cancelSearchJob();
    void startSearchJob();
    QDate timelineDate(const QUrl &url) const;
    void setCurrentUrl(const QUrl &url);
    void setLoading(bool loading);
    void setErrorString(const QString &error);
    void setOperationBusy(bool busy);
    void setOperationProgress(int progress);
    void setOperationMessage(const QString &message);
    void rebuildFromLister();
    void rebuildVisibleItems();
    void sortItems(QVector<KFileItem> &items) const;
    void sortRecentItems(QVector<KFileItem> &items) const;
    void sortSearchItems(QVector<KFileItem> &items, const QString &query) const;
    QString propertiesTextForItem(const KFileItem &item, const QString &sizeText) const;
    int searchRank(const KFileItem &item, const QString &query) const;
    QString searchDisplayName(const KFileItem &item) const;
    QVector<int> normalizedRows(const QVariantList &rows) const;
    QList<QUrl> urlsForRows(const QVector<int> &rows) const;
    void startDragForRow(int row);
    int fileRowAt(QQuickWindow *window, const QPointF &scenePosition) const;
    int fileRowAtItem(QQuickItem *root, const QPointF &scenePosition) const;
    void watchJob(KJob *job, const QString &successMessage, const QUrl &selectUrl = {});
    QUrl childUrl(const QString &name) const;
    QUrl validatedChildUrl(const QString &name, QString *error) const;
    QList<QUrl> dropUrlsFromValues(const QVariantList &values) const;
    bool validateDrop(
        const QList<QUrl> &urls,
        const QUrl &destination,
        QString *error,
        bool rejectSameParent = true) const;
    static Qt::DropAction naturalDragAction(const QList<QUrl> &urls);

    KCoreDirLister m_lister;
    QPointer<KIO::ListJob> m_recentJob;
    QPointer<KIO::ListJob> m_searchJob;
    QPointer<KIO::DirectorySizeJob> m_propertiesJob;
    QPointer<KJob> m_activeOperation;
    QTimer m_searchDebounce;
    QDate m_recentTargetDate;
    bool m_recentRolling = false;
    QVector<KFileItem> m_sourceItems;
    QVector<KFileItem> m_searchItems;
    QVector<KFileItem> m_items;
    QUrl m_currentUrl;
    QUrl m_searchRootUrl;
    QVector<QUrl> m_history;
    int m_historyIndex = -1;
    int m_dragCandidateRow = -1;
    QPointF m_dragStartPosition;
    QVector<int> m_selectedRows;
    bool m_loading = false;
    QString m_errorString;
    bool m_showHidden = false;
    QString m_searchQuery;
    QString m_sortKey = QStringLiteral("name");
    bool m_sortDescending = false;
    bool m_operationBusy = false;
    int m_operationProgress = -1;
    QString m_operationMessage;
    QUrl m_pendingSelectionUrl;
};
