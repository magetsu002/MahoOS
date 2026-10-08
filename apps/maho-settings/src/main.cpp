#include "MahoPalette.h"
#include "MahoSettingsBridge.h"

#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQmlError>
#include <QQuickStyle>

#include <cstring>
#include <iostream>

#ifndef MAHO_SETTINGS_SOURCE_FINGERPRINT
#error "Maho Settings must be built with an embedded source fingerprint"
#endif

[[gnu::used]] static constexpr char kMahoSettingsArtifactProvenance[] =
    "MAHO_SETTINGS_SOURCE_FINGERPRINT=" MAHO_SETTINGS_SOURCE_FINGERPRINT;

int main(int argc, char *argv[])
{
    if (argc == 2 && std::strcmp(argv[1], "--source-fingerprint") == 0) {
        std::cout << MAHO_SETTINGS_SOURCE_FINGERPRINT << '\n';
        return 0;
    }

    QGuiApplication application(argc, argv);
    application.setApplicationName(QStringLiteral("Maho Settings"));
    application.setOrganizationName(QStringLiteral("MahoOS"));
    application.setDesktopFileName(QStringLiteral("io.maho.Settings"));
    QQuickStyle::setStyle(QStringLiteral("Basic"));

    MahoPalette palette;
    MahoSettingsBridge settings;

    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty(QStringLiteral("mahoPalette"), &palette);
    engine.rootContext()->setContextProperty(QStringLiteral("settingsBridge"), &settings);

    QObject::connect(&engine, &QQmlApplicationEngine::warnings,
                     [](const QList<QQmlError> &warnings) {
        for (const QQmlError &warning : warnings)
            std::cerr << warning.toString().toStdString() << std::endl;
    });

    QObject::connect(
        &engine,
        &QQmlApplicationEngine::objectCreationFailed,
        &application,
        [] { QCoreApplication::exit(1); },
        Qt::QueuedConnection);
    engine.loadFromModule(QStringLiteral("Maho.Settings"), QStringLiteral("Main"));
    return application.exec();
}
