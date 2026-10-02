#pragma once

#include <QObject>
#include <QProcess>
#include <QVariantList>
#include <QVariantMap>

class MahoSettingsBridge final : public QObject
{
    Q_OBJECT
    Q_PROPERTY(QVariantMap state READ state NOTIFY stateChanged)
    Q_PROPERTY(QVariantList searchResults READ searchResults NOTIFY searchResultsChanged)
    Q_PROPERTY(bool loading READ loading NOTIFY loadingChanged)
    Q_PROPERTY(bool actionBusy READ actionBusy NOTIFY actionBusyChanged)
    Q_PROPERTY(QString error READ error NOTIFY errorChanged)

public:
    explicit MahoSettingsBridge(QObject *parent = nullptr);

    QVariantMap state() const { return m_state; }
    QVariantList searchResults() const { return m_searchResults; }
    bool loading() const { return m_loading; }
    bool actionBusy() const { return m_actionBusy; }
    QString error() const { return m_error; }

    Q_INVOKABLE void refresh();
    Q_INVOKABLE void search(const QString &query);
    Q_INVOKABLE void perform(const QString &action, const QVariantMap &payload = {});

signals:
    void stateChanged();
    void searchResultsChanged();
    void loadingChanged();
    void actionBusyChanged();
    void errorChanged();
    void actionFinished(const QString &action, bool ok, const QString &message, const QVariantMap &result);

private:
    QString pythonProgram() const;
    QString backendPath() const;
    void refreshSection(const QString &section);
    void startRefresh(const QString &section);
    void finishRefresh();
    static QString sectionForAction(const QString &action);
    void setLoading(bool value);
    void setActionBusy(bool value);
    void setError(const QString &value);
    static QVariantMap parseObject(const QByteArray &data, QString *error);

    QVariantMap m_state;
    QVariantList m_searchResults;
    bool m_loading = false;
    bool m_actionBusy = false;
    QString m_error;
    QString m_pendingAction;
    QString m_snapshotSection;
    QString m_pendingRefreshSection;

    QProcess m_snapshotProcess;
    QProcess m_searchProcess;
    QProcess m_actionProcess;
};
