#include "MahoDirectoryModel.h"

#include <QApplication>
#include <QFile>
#include <QFileInfo>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>

class MahoDirectoryModelTest final : public QObject
{
    Q_OBJECT

private:
    static QUrl dirUrl(const QString &path)
    {
        return QUrl::fromLocalFile(path);
    }

    static QVariantList urls(std::initializer_list<QUrl> values)
    {
        QVariantList result;
        for (const QUrl &url : values)
            result.append(url);
        return result;
    }

    static void writeFile(const QString &path, const QByteArray &contents = "x")
    {
        QFile file(path);
        QVERIFY2(file.open(QIODevice::WriteOnly | QIODevice::Truncate),
                 qPrintable(file.errorString()));
        QCOMPARE(file.write(contents), contents.size());
    }

    static void openAndSettle(MahoDirectoryModel &model, const QString &path)
    {
        model.openUrl(dirUrl(path));
        QTRY_COMPARE_WITH_TIMEOUT(model.currentUrl(), dirUrl(path), 5000);
        QTRY_VERIFY_WITH_TIMEOUT(!model.loading(), 5000);
    }

private slots:
    void createFileUsesBackendAndRejectsBadTargets()
    {
        QTemporaryDir temp;
        QVERIFY(temp.isValid());

        MahoDirectoryModel model;
        openAndSettle(model, temp.path());

        QSignalSpy selectionSpy(&model, &MahoDirectoryModel::selectRowRequested);
        model.createFile(QStringLiteral("created.txt"));
        QTRY_COMPARE_WITH_TIMEOUT(model.operationMessage(), QStringLiteral("File created"), 5000);
        QTRY_VERIFY_WITH_TIMEOUT(QFileInfo::exists(temp.filePath(QStringLiteral("created.txt"))), 5000);
        QTRY_VERIFY_WITH_TIMEOUT(selectionSpy.count() > 0, 5000);

        model.createFile(QStringLiteral("   "));
        QCOMPARE(model.operationMessage(), QStringLiteral("Name cannot be empty."));

        model.createFile(QStringLiteral("../escape"));
        QCOMPARE(model.operationMessage(), QStringLiteral("That name is not valid here."));

        writeFile(temp.filePath(QStringLiteral("exists.txt")));
        model.createFile(QStringLiteral("exists.txt"));
        QCOMPARE(model.operationMessage(), QStringLiteral("An item named exists.txt already exists."));

        const QString locked = temp.filePath(QStringLiteral("locked"));
        QVERIFY(QDir().mkdir(locked));
        QVERIFY(QFile::setPermissions(
            locked,
            QFileDevice::ReadOwner | QFileDevice::ExeOwner));
        openAndSettle(model, locked);
        QVERIFY(!model.canMutateCurrentDirectory());
        model.createFile(QStringLiteral("blocked.txt"));
        QCOMPARE(model.operationMessage(), QStringLiteral("Create items from a writable local folder."));
        QVERIFY(!QFileInfo::exists(locked + QStringLiteral("/blocked.txt")));

        QVERIFY(QFile::setPermissions(
            locked,
            QFileDevice::ReadOwner | QFileDevice::WriteOwner | QFileDevice::ExeOwner));
    }

    void validatesRealFolderDestinations()
    {
        QTemporaryDir temp;
        QVERIFY(temp.isValid());

        const QString src = temp.filePath(QStringLiteral("src"));
        const QString dest = temp.filePath(QStringLiteral("dest"));
        const QString folder = src + QStringLiteral("/folder");
        const QString child = folder + QStringLiteral("/child");
        QVERIFY(QDir().mkpath(child));
        QVERIFY(QDir().mkpath(dest));

        const QString first = src + QStringLiteral("/a.txt");
        const QString second = src + QStringLiteral("/b.txt");
        writeFile(first);
        writeFile(second);

        MahoDirectoryModel model;
        QVERIFY(model.canDropUrlsTo(urls({dirUrl(first)}), dirUrl(dest)));
        QVERIFY(model.canDropUrlsTo(urls({dirUrl(folder)}), dirUrl(dest)));
        QVERIFY(model.canDropUrlsTo(urls({dirUrl(first), dirUrl(second)}), dirUrl(dest)));

        QVERIFY(!model.canDropUrlsTo(urls({dirUrl(folder)}), dirUrl(folder)));
        QVERIFY(!model.canDropUrlsTo(urls({dirUrl(folder)}), dirUrl(child)));
        QVERIFY(!model.canDropUrlsTo(urls({dirUrl(first)}), dirUrl(src)));
        QVERIFY(!model.canDropUrlsTo(urls({dirUrl(first)}), QUrl(QStringLiteral("https://example.invalid/"))));

        const QString locked = temp.filePath(QStringLiteral("locked-dest"));
        QVERIFY(QDir().mkdir(locked));
        QVERIFY(QFile::setPermissions(
            locked,
            QFileDevice::ReadOwner | QFileDevice::ExeOwner));
        QVERIFY(!model.canDropUrlsTo(urls({dirUrl(first)}), dirUrl(locked)));
        QVERIFY(QFile::setPermissions(
            locked,
            QFileDevice::ReadOwner | QFileDevice::WriteOwner | QFileDevice::ExeOwner));
    }

    void executesCopyMoveAndMultiMoveThroughKio()
    {
        QTemporaryDir temp;
        QVERIFY(temp.isValid());

        const QString current = temp.filePath(QStringLiteral("current"));
        const QString source = temp.filePath(QStringLiteral("source"));
        const QString moveDest = temp.filePath(QStringLiteral("move-dest"));
        const QString copyDest = temp.filePath(QStringLiteral("copy-dest"));
        const QString multiDest = temp.filePath(QStringLiteral("multi-dest"));
        QVERIFY(QDir().mkpath(current));
        QVERIFY(QDir().mkpath(source));
        QVERIFY(QDir().mkpath(moveDest));
        QVERIFY(QDir().mkpath(copyDest));
        QVERIFY(QDir().mkpath(multiDest));

        MahoDirectoryModel model;
        openAndSettle(model, current);

        const QString moveFile = source + QStringLiteral("/move.txt");
        writeFile(moveFile, "move");
        model.dropUrls(urls({dirUrl(moveFile)}), dirUrl(moveDest), Qt::MoveAction);
        QTRY_COMPARE_WITH_TIMEOUT(model.operationMessage(), QStringLiteral("Moved here"), 5000);
        QTRY_VERIFY_WITH_TIMEOUT(QFileInfo::exists(moveDest + QStringLiteral("/move.txt")), 5000);
        QVERIFY(!QFileInfo::exists(moveFile));

        const QString copyFolder = source + QStringLiteral("/copy-folder");
        QVERIFY(QDir().mkpath(copyFolder));
        writeFile(copyFolder + QStringLiteral("/inside.txt"), "copy");
        model.dropUrls(urls({dirUrl(copyFolder)}), dirUrl(copyDest), Qt::CopyAction);
        QTRY_COMPARE_WITH_TIMEOUT(model.operationMessage(), QStringLiteral("Copied here"), 5000);
        QTRY_VERIFY_WITH_TIMEOUT(
            QFileInfo::exists(copyDest + QStringLiteral("/copy-folder/inside.txt")), 5000);
        QVERIFY(QFileInfo::exists(copyFolder + QStringLiteral("/inside.txt")));

        const QString multiA = source + QStringLiteral("/multi-a.txt");
        const QString multiB = source + QStringLiteral("/multi-b.txt");
        writeFile(multiA, "a");
        writeFile(multiB, "b");
        model.dropUrls(
            urls({dirUrl(multiA), dirUrl(multiB)}),
            dirUrl(multiDest),
            Qt::MoveAction);
        QTRY_COMPARE_WITH_TIMEOUT(model.operationMessage(), QStringLiteral("Moved here"), 5000);
        QTRY_VERIFY_WITH_TIMEOUT(
            QFileInfo::exists(multiDest + QStringLiteral("/multi-a.txt"))
                && QFileInfo::exists(multiDest + QStringLiteral("/multi-b.txt")),
            5000);
        QVERIFY(!QFileInfo::exists(multiA));
        QVERIFY(!QFileInfo::exists(multiB));
    }
};

QTEST_MAIN(MahoDirectoryModelTest)
#include "MahoDirectoryModelTest.moc"
