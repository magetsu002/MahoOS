#include "MahoSettingsBridge.h"

#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QStandardPaths>

MahoSettingsBridge::MahoSettingsBridge(QObject *parent)
    : QObject(parent)
{
    connect(&m_snapshotProcess, &QProcess::finished, this,
            [this](int, QProcess::ExitStatus) {
        QString parseError;
        const QVariantMap payload = parseObject(m_snapshotProcess.readAllStandardOutput(), &parseError);
        setLoading(false);
        if (!parseError.isEmpty()) {
            setError(parseError);
            return;
        }
        if (!payload.value(QStringLiteral("ok")).toBool()) {
            setError(payload.value(QStringLiteral("error")).toString());
            return;
        }
        m_state = payload;
        m_state.remove(QStringLiteral("ok"));
        emit stateChanged();
        setError({});
    });

    connect(&m_searchProcess, &QProcess::finished, this,
            [this](int, QProcess::ExitStatus) {
        QString parseError;
        const QVariantMap payload = parseObject(m_searchProcess.readAllStandardOutput(), &parseError);
        if (!parseError.isEmpty() || !payload.value(QStringLiteral("ok")).toBool()) {
            m_searchResults.clear();
        } else {
            m_searchResults = payload.value(QStringLiteral("results")).toList();
        }
        emit searchResultsChanged();
    });

    connect(&m_actionProcess, &QProcess::finished, this,
            [this](int, QProcess::ExitStatus) {
        QString parseError;
        QVariantMap payload = parseObject(m_actionProcess.readAllStandardOutput(), &parseError);
        const QString action = m_pendingAction;
        m_pendingAction.clear();
        setActionBusy(false);
        if (!parseError.isEmpty()) {
            setError(parseError);
            emit actionFinished(action, false, parseError, {});
            return;
        }
        const bool ok = payload.value(QStringLiteral("ok")).toBool();
        const QString message = ok
            ? payload.value(QStringLiteral("message")).toString()
            : payload.value(QStringLiteral("error")).toString();
        if (!ok)
            setError(message);
        else
            setError({});
        emit actionFinished(action, ok, message, payload);
        if (ok)
            refresh();
    });

    refresh();
}

QString MahoSettingsBridge::pythonProgram() const
{
    const QString python = QStandardPaths::findExecutable(QStringLiteral("python3"));
    return python.isEmpty() ? QStringLiteral("python3") : python;
}

QString MahoSettingsBridge::backendPath() const
{
    const QString requested = qEnvironmentVariable("MAHO_SETTINGS_BACKEND");
    if (!requested.isEmpty())
        return requested;
    const QString found = QStandardPaths::findExecutable(QStringLiteral("maho-settings-backend"));
    return found.isEmpty() ? QStringLiteral("maho-settings-backend") : found;
}

void MahoSettingsBridge::refresh()
{
    if (m_snapshotProcess.state() != QProcess::NotRunning)
        return;
    setLoading(true);
    m_snapshotProcess.setProgram(pythonProgram());
    m_snapshotProcess.setArguments({backendPath(), QStringLiteral("snapshot"), QStringLiteral("all")});
    m_snapshotProcess.start();
}

void MahoSettingsBridge::search(const QString &query)
{
    if (query.trimmed().isEmpty()) {
        m_searchResults.clear();
        emit searchResultsChanged();
        return;
    }
    if (m_searchProcess.state() != QProcess::NotRunning) {
        m_searchProcess.kill();
        m_searchProcess.waitForFinished(100);
    }
    m_searchProcess.setProgram(pythonProgram());
    m_searchProcess.setArguments({backendPath(), QStringLiteral("search"), query});
    m_searchProcess.start();
}

void MahoSettingsBridge::perform(const QString &action, const QVariantMap &payload)
{
    if (m_actionProcess.state() != QProcess::NotRunning)
        return;
    m_pendingAction = action;
    setActionBusy(true);
    const QByteArray json = QJsonDocument(QJsonObject::fromVariantMap(payload)).toJson(QJsonDocument::Compact);
    m_actionProcess.setProgram(pythonProgram());
    m_actionProcess.setArguments({
        backendPath(),
        QStringLiteral("action"),
        action,
        QString::fromUtf8(json),
    });
    m_actionProcess.start();
}

void MahoSettingsBridge::setLoading(bool value)
{
    if (m_loading == value)
        return;
    m_loading = value;
    emit loadingChanged();
}

void MahoSettingsBridge::setActionBusy(bool value)
{
    if (m_actionBusy == value)
        return;
    m_actionBusy = value;
    emit actionBusyChanged();
}

void MahoSettingsBridge::setError(const QString &value)
{
    if (m_error == value)
        return;
    m_error = value;
    emit errorChanged();
}

QVariantMap MahoSettingsBridge::parseObject(const QByteArray &data, QString *error)
{
    QJsonParseError parseError;
    const QJsonDocument document = QJsonDocument::fromJson(data, &parseError);
    if (parseError.error != QJsonParseError::NoError || !document.isObject()) {
        if (error)
            *error = QStringLiteral("Settings backend returned an invalid response.");
        return {};
    }
    if (error)
        error->clear();
    return document.object().toVariantMap();
}
