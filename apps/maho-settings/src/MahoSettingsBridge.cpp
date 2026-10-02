#include "MahoSettingsBridge.h"

#include <QDir>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QStandardPaths>
#include <QTimer>

MahoSettingsBridge::MahoSettingsBridge(QObject *parent)
    : QObject(parent)
{
    connect(&m_snapshotProcess, &QProcess::finished, this,
            [this](int, QProcess::ExitStatus) {
        const QString completedSection = m_snapshotSection;
        m_snapshotSection.clear();

        QString parseError;
        const QVariantMap payload = parseObject(m_snapshotProcess.readAllStandardOutput(), &parseError);
        if (!parseError.isEmpty()) {
            setError(parseError);
        } else if (!payload.value(QStringLiteral("ok")).toBool()) {
            setError(payload.value(QStringLiteral("error")).toString());
        } else {
            if (completedSection == QStringLiteral("all")) {
                m_state = payload;
                m_state.remove(QStringLiteral("ok"));
            } else {
                const QVariant sectionValue = payload.value(completedSection);
                if (sectionValue.canConvert<QVariantMap>())
                    m_state.insert(completedSection, sectionValue);
            }
            emit stateChanged();
            setError({});
        }

        finishRefresh();
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

        if (!parseError.isEmpty()) {
            setActionBusy(false);
            setError(parseError);
            emit actionFinished(action, false, parseError, {});
            return;
        }

        const bool ok = payload.value(QStringLiteral("ok")).toBool();
        const QString message = ok
            ? payload.value(QStringLiteral("message")).toString()
            : payload.value(QStringLiteral("error")).toString();

        if (!ok) {
            setActionBusy(false);
            setError(message);
            emit actionFinished(action, false, message, payload);
            return;
        }

        setError({});
        const QString section = sectionForAction(action);
        const QVariant confirmedState = payload.value(QStringLiteral("state"));

        if (section != QStringLiteral("all") && confirmedState.canConvert<QVariantMap>()) {
            m_state.insert(section, confirmedState);
            emit stateChanged();
            setActionBusy(false);
        } else {
            // Keep the interaction in its optimistic state until the owner's
            // verified readback lands. Dropping busy before this refresh makes
            // switches visually snap back and then forward again.
            refreshSection(section);
        }

        emit actionFinished(action, true, message, payload);
    });

    connect(&m_wallpaperPickerProcess, &QProcess::finished, this,
            [this](int, QProcess::ExitStatus) {
        // The picker applies the wallpaper in a detached helper just before it
        // closes. Give that existing owner a short convergence window, then
        // re-observe Appearance rather than guessing the selected result.
        QTimer::singleShot(1400, this, [this] {
            refreshSection(QStringLiteral("appearance"));
        });
    });

    connect(&m_wallpaperPickerProcess, &QProcess::errorOccurred, this,
            [this](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart)
            setError(QStringLiteral("Wallpaper picker is unavailable."));
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
    refreshSection(QStringLiteral("all"));
}

void MahoSettingsBridge::refreshSection(const QString &section)
{
    const QString requested = section.isEmpty() ? QStringLiteral("all") : section;

    if (m_snapshotProcess.state() != QProcess::NotRunning) {
        if (m_pendingRefreshSection.isEmpty()) {
            m_pendingRefreshSection = requested;
        } else if (m_pendingRefreshSection != requested) {
            // Two different sections have changed while an observation is
            // already in flight. One bounded full refresh is simpler and safer
            // than allowing either section to remain stale.
            m_pendingRefreshSection = QStringLiteral("all");
        }
        return;
    }

    startRefresh(requested);
}

void MahoSettingsBridge::startRefresh(const QString &section)
{
    m_snapshotSection = section;
    if (section == QStringLiteral("all"))
        setLoading(true);

    m_snapshotProcess.setProgram(pythonProgram());
    m_snapshotProcess.setArguments({backendPath(), QStringLiteral("snapshot"), section});
    m_snapshotProcess.start();
}

void MahoSettingsBridge::finishRefresh()
{
    if (!m_pendingRefreshSection.isEmpty()) {
        const QString nextSection = m_pendingRefreshSection;
        m_pendingRefreshSection.clear();
        startRefresh(nextSection);
        return;
    }

    setLoading(false);
    if (m_actionProcess.state() == QProcess::NotRunning)
        setActionBusy(false);
}

QString MahoSettingsBridge::sectionForAction(const QString &action)
{
    if (action.startsWith(QStringLiteral("appearance.")))
        return QStringLiteral("appearance");
    if (action.startsWith(QStringLiteral("display.")))
        return QStringLiteral("displays");
    if (action.startsWith(QStringLiteral("sound.")))
        return QStringLiteral("sound");
    if (action.startsWith(QStringLiteral("input.")))
        return QStringLiteral("input");
    if (action.startsWith(QStringLiteral("notification.")))
        return QStringLiteral("notifications");
    if (action.startsWith(QStringLiteral("region.")))
        return QStringLiteral("region");
    if (action.startsWith(QStringLiteral("applications.")))
        return QStringLiteral("applications");
    if (action.startsWith(QStringLiteral("power.")))
        return QStringLiteral("power");
    return QStringLiteral("all");
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

void MahoSettingsBridge::openWallpaperPicker()
{
    if (m_wallpaperPickerProcess.state() != QProcess::NotRunning)
        return;

    QString picker = QDir::homePath() + QStringLiteral("/.local/bin/qs-wallpaper-picker");
    if (!QFileInfo(picker).isExecutable())
        picker = QStandardPaths::findExecutable(QStringLiteral("qs-wallpaper-picker"));

    if (picker.isEmpty()) {
        setError(QStringLiteral("Wallpaper picker is unavailable."));
        return;
    }

    setError({});
    m_wallpaperPickerProcess.setProgram(picker);
    m_wallpaperPickerProcess.setArguments({});
    m_wallpaperPickerProcess.start();
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
