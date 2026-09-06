#include "MahoDirectoryModel.h"
#include "MahoPalette.h"
#include "MahoPlacesController.h"

#include <QApplication>
#include <QCommandLineParser>
#include <QCommandLineOption>
#include <QFileInfo>
#include <QIcon>
#include <QImage>
#include <QPainter>
#include <QPixmap>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickImageProvider>
#include <QQuickStyle>
#include <QTimer>
#include <QUrl>

#include <KFilePlacesModel>

#include <cstring>
#include <iostream>

#ifndef MAHO_FILES_SOURCE_FINGERPRINT
#error "Maho Files must be built with an embedded source fingerprint"
#endif

[[gnu::used]] static constexpr char kMahoFilesArtifactProvenance[] =
    "MAHO_FILES_SOURCE_FINGERPRINT=" MAHO_FILES_SOURCE_FINGERPRINT;

class ThemeIconProvider final : public QQuickImageProvider
{
public:
    explicit ThemeIconProvider(MahoPalette *palette)
        : QQuickImageProvider(QQuickImageProvider::Pixmap)
        , m_palette(palette)
    {
    }

    QPixmap requestPixmap(const QString &id, QSize *size, const QSize &requestedSize) override
    {
        const QString decoded = QUrl::fromPercentEncoding(id.toUtf8());
        QIcon icon;

        if (QFileInfo::exists(decoded))
            icon = QIcon(decoded);
        else
            icon = QIcon::fromTheme(decoded);

        if (icon.isNull())
            icon = QIcon::fromTheme(QStringLiteral("unknown"));

        QSize target = requestedSize.isValid() ? requestedSize : QSize(64, 64);
        if (target.width() <= 0)
            target.setWidth(64);
        if (target.height() <= 0)
            target.setHeight(64);

        QPixmap pixmap;
        if (m_palette && shouldTintUiIcon(decoded))
            pixmap = renderUiIcon(icon, target, m_palette->foreground());
        else
            pixmap = renderArtwork(icon, target);

        if (size)
            *size = pixmap.size();
        return pixmap;
    }

private:
    static QSize multipliedSize(const QSize &size, int factor)
    {
        return QSize(qMax(1, size.width() * factor),
                     qMax(1, size.height() * factor));
    }

    static QPixmap renderArtwork(const QIcon &icon, const QSize &target)
    {
        // Ask the icon engine for a larger source first. SVG themes render at the
        // larger size directly, while raster themes can select a denser asset.
        // The explicit high-quality downsample is sharper than letting several
        // layers independently stretch a small pixmap.
        const QSize sourceSize = multipliedSize(target, 2);
        const QPixmap source = icon.pixmap(sourceSize);
        if (source.isNull())
            return {};

        if (source.size() == target)
            return source;

        return source.scaled(target,
                             Qt::KeepAspectRatio,
                             Qt::SmoothTransformation);
    }

    static QRect visibleAlphaBounds(const QImage &image)
    {
        if (image.isNull())
            return {};

        int left = image.width();
        int top = image.height();
        int right = -1;
        int bottom = -1;

        for (int y = 0; y < image.height(); ++y) {
            const auto *scanline = reinterpret_cast<const QRgb *>(image.constScanLine(y));
            for (int x = 0; x < image.width(); ++x) {
                // Ignore tiny antialiasing dust at the outer SVG viewport edge.
                if (qAlpha(scanline[x]) <= 10)
                    continue;

                left = qMin(left, x);
                top = qMin(top, y);
                right = qMax(right, x);
                bottom = qMax(bottom, y);
            }
        }

        if (right < left || bottom < top)
            return {};

        return QRect(QPoint(left, top), QPoint(right, bottom));
    }

    static QPixmap renderUiIcon(const QIcon &icon,
                                const QSize &target,
                                const QColor &foreground)
    {
        // UI icons need stronger optical normalization than file artwork. Theme
        // SVGs often contain large transparent viewBox padding which made a
        // nominal 17 px menu icon look like a 6–8 px speck. Render large, tint,
        // crop the transparent bounds, then place the unchanged shape into a
        // consistent optical box.
        const QSize sourceSize = multipliedSize(target, 4);
        QPixmap source = icon.pixmap(sourceSize);
        if (source.isNull())
            return {};

        QPixmap tinted(source.size());
        tinted.fill(Qt::transparent);

        {
            QPainter painter(&tinted);
            painter.setRenderHint(QPainter::Antialiasing, true);
            painter.setRenderHint(QPainter::SmoothPixmapTransform, true);
            painter.drawPixmap(0, 0, source);
            painter.setCompositionMode(QPainter::CompositionMode_SourceIn);

            QColor tint = foreground;
            tint.setAlphaF(0.96);
            painter.fillRect(tinted.rect(), tint);
        }

        const QImage image = tinted.toImage().convertToFormat(QImage::Format_ARGB32_Premultiplied);
        const QRect bounds = visibleAlphaBounds(image);
        if (bounds.isEmpty())
            return tinted.scaled(target,
                                 Qt::KeepAspectRatio,
                                 Qt::SmoothTransformation);

        const QPixmap cropped = QPixmap::fromImage(image.copy(bounds));

        // Leave a small, consistent optical inset. This keeps menu/sidebar
        // actions visually equal to the 20 px Maho toolbar glyphs without
        // changing the original icon silhouette.
        const QSize opticalBox(qMax(1, qRound(target.width() * 0.92)),
                               qMax(1, qRound(target.height() * 0.92)));
        const QPixmap scaled = cropped.scaled(opticalBox,
                                              Qt::KeepAspectRatio,
                                              Qt::SmoothTransformation);

        QPixmap normalized(target);
        normalized.fill(Qt::transparent);

        {
            QPainter painter(&normalized);
            painter.setRenderHint(QPainter::Antialiasing, true);
            painter.setRenderHint(QPainter::SmoothPixmapTransform, true);
            const QPoint origin((target.width() - scaled.width()) / 2,
                                (target.height() - scaled.height()) / 2);
            painter.drawPixmap(origin, scaled);
        }

        return normalized;
    }

    static bool shouldTintUiIcon(const QString &name)
    {
        if (name.startsWith(QStringLiteral("go-"))
            || name.startsWith(QStringLiteral("edit-"))
            || name.startsWith(QStringLiteral("view-"))) {
            return true;
        }

        if (name.contains(QStringLiteral("recent"), Qt::CaseInsensitive)
            || name.contains(QStringLiteral("timeline"), Qt::CaseInsensitive)
            || name.contains(QStringLiteral("calendar"), Qt::CaseInsensitive)) {
            return true;
        }

        return name == QStringLiteral("application-menu")
            || name == QStringLiteral("folder-new")
            || name == QStringLiteral("folder-open")
            || name == QStringLiteral("document-open")
            || name == QStringLiteral("user-trash")
            || name == QStringLiteral("media-eject")
            || name == QStringLiteral("dialog-error");
    }

    MahoPalette *m_palette = nullptr;
};

int main(int argc, char *argv[])
{
    if (argc == 2 && std::strcmp(argv[1], "--source-fingerprint") == 0) {
        std::cout << MAHO_FILES_SOURCE_FINGERPRINT << '\n';
        return 0;
    }

    QCoreApplication::setOrganizationName(QStringLiteral("MahoOS"));
    QCoreApplication::setOrganizationDomain(QStringLiteral("maho.local"));
    QCoreApplication::setApplicationName(QStringLiteral("Maho Files"));
    QApplication::setDesktopFileName(QStringLiteral("io.maho.Files"));

    QApplication application(argc, argv);

    QQuickStyle::setStyle(QStringLiteral("Basic"));

    QCommandLineParser parser;
    parser.setApplicationDescription(QStringLiteral("Maho Files — native QML frontend over KDE KIO"));
    parser.addHelpOption();
    parser.addVersionOption();
    const QCommandLineOption shutdownTestOption(
        QStringLiteral("test-shutdown-after-load"),
        QStringLiteral("Exit after the initial model load for shutdown diagnostics."));
    parser.addOption(shutdownTestOption);
    parser.addPositionalArgument(QStringLiteral("location"), QStringLiteral("Folder or KIO URL to open."), QStringLiteral("[location]"));
    parser.process(application);

    MahoDirectoryModel directoryModel;
    MahoPalette palette;
    KFilePlacesModel placesModel;
    MahoPlacesController placesController(&placesModel, &directoryModel);

    const QStringList positional = parser.positionalArguments();
    if (!positional.isEmpty())
        directoryModel.openLocation(positional.constFirst());

    QQmlApplicationEngine engine;
    engine.addImageProvider(QStringLiteral("mahoicons"), new ThemeIconProvider(&palette));
    engine.rootContext()->setContextProperty(QStringLiteral("directoryModel"), &directoryModel);
    engine.rootContext()->setContextProperty(QStringLiteral("placesModel"), &placesModel);
    engine.rootContext()->setContextProperty(QStringLiteral("placesController"), &placesController);
    engine.rootContext()->setContextProperty(QStringLiteral("mahoPalette"), &palette);

    QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed,
                     &application, []() { QCoreApplication::exit(1); },
                     Qt::QueuedConnection);

    engine.loadFromModule(QStringLiteral("Maho.Files"), QStringLiteral("Main"));
    if (parser.isSet(shutdownTestOption))
        QTimer::singleShot(350, &application, &QCoreApplication::quit);
    return application.exec();
}
