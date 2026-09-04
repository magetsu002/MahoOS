#include "MahoDirectoryModel.h"
#include "MahoPalette.h"

#include <QCommandLineParser>
#include <QFileInfo>
#include <QGuiApplication>
#include <QIcon>
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
    ThemeIconProvider()
        : QQuickImageProvider(QQuickImageProvider::Pixmap)
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

        const QPixmap pixmap = icon.pixmap(target);
        if (size)
            *size = pixmap.size();
        return pixmap;
    }
};

int main(int argc, char *argv[])
{
    QGuiApplication application(argc, argv);
    QCoreApplication::setOrganizationName(QStringLiteral("MahoOS"));
    QCoreApplication::setOrganizationDomain(QStringLiteral("maho.local"));
    QCoreApplication::setApplicationName(QStringLiteral("Maho Files"));
    QGuiApplication::setDesktopFileName(QStringLiteral("io.maho.Files"));

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

    const QStringList positional = parser.positionalArguments();
    if (!positional.isEmpty())
        directoryModel.openLocation(positional.constFirst());

    QQmlApplicationEngine engine;
    engine.addImageProvider(QStringLiteral("mahoicons"), new ThemeIconProvider);
    engine.rootContext()->setContextProperty(QStringLiteral("directoryModel"), &directoryModel);
    engine.rootContext()->setContextProperty(QStringLiteral("placesModel"), &placesModel);
    engine.rootContext()->setContextProperty(QStringLiteral("mahoPalette"), &palette);

    QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed,
                     &application, []() { QCoreApplication::exit(1); },
                     Qt::QueuedConnection);

    engine.loadFromModule(QStringLiteral("Maho.Files"), QStringLiteral("Main"));
    return application.exec();
}
