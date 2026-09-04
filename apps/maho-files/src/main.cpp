#include "MahoDirectoryModel.h"
#include "MahoPalette.h"
#include "MahoPlacesController.h"

#include <QApplication>
#include <QCommandLineParser>
#include <QFileInfo>
#include <QIcon>
#include <QPainter>
#include <QPixmap>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickImageProvider>
#include <QQuickStyle>
#include <QUrl>

#include <KFilePlacesModel>

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

        QPixmap pixmap = icon.pixmap(target);
        if (m_palette && shouldTintUiIcon(decoded) && !pixmap.isNull()) {
            QPixmap tinted(pixmap.size());
            tinted.fill(Qt::transparent);

            QPainter painter(&tinted);
            painter.setRenderHint(QPainter::Antialiasing, true);
            painter.drawPixmap(0, 0, pixmap);
            painter.setCompositionMode(QPainter::CompositionMode_SourceIn);

            QColor tint = m_palette->foreground();
            tint.setAlphaF(0.94);
            painter.fillRect(tinted.rect(), tint);
            painter.end();

            pixmap = tinted;
        }

        if (size)
            *size = pixmap.size();
        return pixmap;
    }

private:
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
    QApplication application(argc, argv);
    QCoreApplication::setOrganizationName(QStringLiteral("MahoOS"));
    QCoreApplication::setOrganizationDomain(QStringLiteral("maho.local"));
    QCoreApplication::setApplicationName(QStringLiteral("Maho Files"));
    QApplication::setDesktopFileName(QStringLiteral("io.maho.Files"));

    QQuickStyle::setStyle(QStringLiteral("Basic"));

    QCommandLineParser parser;
    parser.setApplicationDescription(QStringLiteral("Maho Files — native QML frontend over KDE KIO"));
    parser.addHelpOption();
    parser.addVersionOption();
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
    return application.exec();
}
