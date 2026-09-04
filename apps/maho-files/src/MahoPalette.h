#pragma once

#include <QColor>
#include <QFileSystemWatcher>
#include <QJsonObject>
#include <QObject>
#include <QString>

class MahoPalette final : public QObject
{
    Q_OBJECT
    Q_PROPERTY(QColor background READ background NOTIFY paletteChanged)
    Q_PROPERTY(QColor surface READ surface NOTIFY paletteChanged)
    Q_PROPERTY(QColor surfaceElevated READ surfaceElevated NOTIFY paletteChanged)
    Q_PROPERTY(QColor foreground READ foreground NOTIFY paletteChanged)
    Q_PROPERTY(QColor muted READ muted NOTIFY paletteChanged)
    Q_PROPERTY(QColor accent READ accent NOTIFY paletteChanged)
    Q_PROPERTY(QColor border READ border NOTIFY paletteChanged)
    Q_PROPERTY(QColor shadow READ shadow NOTIFY paletteChanged)
    Q_PROPERTY(QString mode READ mode NOTIFY paletteChanged)

public:
    explicit MahoPalette(QObject *parent = nullptr);

    QColor background() const;
    QColor surface() const;
    QColor surfaceElevated() const;
    QColor foreground() const;
    QColor muted() const;
    QColor accent() const;
    QColor border() const;
    QColor shadow() const;
    QString mode() const;

    Q_INVOKABLE void reload();

signals:
    void paletteChanged();

private:
    QColor readColor(const QJsonObject &semantic,
                     const QJsonObject &colors,
                     const QString &semanticKey,
                     const QString &legacyKey,
                     const QColor &fallback) const;
    void watchPalette();

    QString m_palettePath;
    QFileSystemWatcher m_watcher;

    QColor m_background {"#151313"};
    QColor m_surface {"#211e1e"};
    QColor m_surfaceElevated {"#2b2727"};
    QColor m_foreground {"#eee9e7"};
    QColor m_muted {"#c9c0bd"};
    QColor m_accent {"#b7a39d"};
    QColor m_border {"#918986"};
    QColor m_shadow {"#000000"};
    QString m_mode {"dark"};
};
