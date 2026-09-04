#pragma once

#include <QAbstractListModel>
#include <QUrl>
#include <QVector>

#include <KCoreDirLister>
#include <KFileItem>

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
    };
    Q_ENUM(Role)

    explicit MahoDirectoryModel(QObject *parent = nullptr);

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

    Q_INVOKABLE void openUrl(const QUrl &url);
    Q_INVOKABLE void openLocation(const QString &location);
    Q_INVOKABLE void openIndex(int row);
    Q_INVOKABLE void goBack();
    Q_INVOKABLE void goForward();
    Q_INVOKABLE void goUp();
    Q_INVOKABLE void goHome();
    Q_INVOKABLE void reload();
    Q_INVOKABLE void setShowHidden(bool show);

signals:
    void currentUrlChanged();
    void loadingChanged();
    void errorStringChanged();
    void historyChanged();
    void showHiddenChanged();

private:
    void navigate(const QUrl &url, bool recordHistory);
    void setCurrentUrl(const QUrl &url);
    void setLoading(bool loading);
    void setErrorString(const QString &error);
    void rebuildFromLister();
    void sortItems();

    KCoreDirLister m_lister;
    QVector<KFileItem> m_items;
    QUrl m_currentUrl;
    QVector<QUrl> m_history;
    int m_historyIndex = -1;
    bool m_loading = false;
    QString m_errorString;
    bool m_showHidden = false;
};
