#include "MahoPalette.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QStandardPaths>

MahoPalette::MahoPalette(QObject *parent)
    : QObject(parent)
{
    const QString cacheHome = qEnvironmentVariableIsSet("XDG_CACHE_HOME")
        ? qEnvironmentVariable("XDG_CACHE_HOME")
        : QDir::homePath() + QStringLiteral("/.cache");

    m_palettePath = QDir(cacheHome).filePath(QStringLiteral("maho/theme/active.json"));

    connect(&m_watcher, &QFileSystemWatcher::fileChanged, this, [this]() {
        reload();
        watchPalette();
    });
    connect(&m_watcher, &QFileSystemWatcher::directoryChanged, this, [this]() {
        reload();
        watchPalette();
    });

    reload();
    watchPalette();
}

QColor MahoPalette::background() const { return m_background; }
QColor MahoPalette::surface() const { return m_surface; }
QColor MahoPalette::surfaceElevated() const { return m_surfaceElevated; }
QColor MahoPalette::foreground() const { return m_foreground; }
QColor MahoPalette::muted() const { return m_muted; }
QColor MahoPalette::accent() const { return m_accent; }
QColor MahoPalette::border() const { return m_border; }
QColor MahoPalette::shadow() const { return m_shadow; }
QString MahoPalette::mode() const { return m_mode; }

void MahoPalette::reload()
{
    QFile file(m_palettePath);
    if (!file.open(QIODevice::ReadOnly))
        return;

    QJsonParseError error;
    const QJsonDocument document = QJsonDocument::fromJson(file.readAll(), &error);
    if (error.error != QJsonParseError::NoError || !document.isObject())
        return;

    const QJsonObject root = document.object();
    const QJsonObject semantic = root.value(QStringLiteral("semantic")).toObject();
    const QJsonObject colors = root.value(QStringLiteral("colors")).toObject();

    const QColor nextBackground = readColor(semantic, colors,
        QStringLiteral("background"), QStringLiteral("background"), m_background);
    const QColor nextSurface = readColor(semantic, colors,
        QStringLiteral("surface"), QStringLiteral("surface_container"), m_surface);
    const QColor nextElevated = readColor(semantic, colors,
        QStringLiteral("surface_elevated"), QStringLiteral("surface_container_high"), m_surfaceElevated);
    const QColor nextForeground = readColor(semantic, colors,
        QStringLiteral("foreground"), QStringLiteral("foreground"), m_foreground);
    const QColor nextMuted = readColor(semantic, colors,
        QStringLiteral("foreground_muted"), QStringLiteral("muted"), m_muted);
    const QColor nextAccent = readColor(semantic, colors,
        QStringLiteral("accent"), QStringLiteral("primary"), m_accent);
    const QColor nextBorder = readColor(semantic, colors,
        QStringLiteral("border"), QStringLiteral("outline"), m_border);
    const QColor nextShadow = readColor(semantic, colors,
        QStringLiteral("shadow"), QString(), m_shadow);
    const QString nextMode = root.value(QStringLiteral("mode")).toString(m_mode);

    if (nextBackground == m_background
        && nextSurface == m_surface
        && nextElevated == m_surfaceElevated
        && nextForeground == m_foreground
        && nextMuted == m_muted
        && nextAccent == m_accent
        && nextBorder == m_border
        && nextShadow == m_shadow
        && nextMode == m_mode) {
        return;
    }

    m_background = nextBackground;
    m_surface = nextSurface;
    m_surfaceElevated = nextElevated;
    m_foreground = nextForeground;
    m_muted = nextMuted;
    m_accent = nextAccent;
    m_border = nextBorder;
    m_shadow = nextShadow;
    m_mode = nextMode;
    emit paletteChanged();
}

QColor MahoPalette::readColor(const QJsonObject &semantic,
                              const QJsonObject &colors,
                              const QString &semanticKey,
                              const QString &legacyKey,
                              const QColor &fallback) const
{
    const QString semanticValue = semantic.value(semanticKey).toString();
    QColor candidate(semanticValue);
    if (candidate.isValid())
        return candidate;

    if (!legacyKey.isEmpty()) {
        const QString legacyValue = colors.value(legacyKey).toString();
        candidate = QColor(legacyValue);
        if (candidate.isValid())
            return candidate;
    }

    return fallback;
}

void MahoPalette::watchPalette()
{
    const QString directory = QFileInfo(m_palettePath).absolutePath();

    if (QFileInfo::exists(directory) && !m_watcher.directories().contains(directory))
        m_watcher.addPath(directory);

    if (QFileInfo::exists(m_palettePath) && !m_watcher.files().contains(m_palettePath))
        m_watcher.addPath(m_palettePath);
}
