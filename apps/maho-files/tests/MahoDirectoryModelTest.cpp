#include "MahoDirectoryModel.h"

#include <QApplication>
#include <QClipboard>
#include <QDir>
#include <QMimeData>
#include <QStandardPaths>
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

    static int findRow(const MahoDirectoryModel &model, const QString &name)
    {
        for (int row = 0; row < model.rowCount(); ++row) {
            if (model.data(model.index(row, 0), MahoDirectoryModel::NameRole).toString() == name)
                return row;
        }
        return -1;
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

    void renameConflictAndStalePathsFailClosed()
    {
        QTemporaryDir temp;
        QVERIFY(temp.isValid());

        const QString current = temp.filePath(QStringLiteral("current"));
        const QString destination = temp.filePath(QStringLiteral("destination"));
        QVERIFY(QDir().mkpath(current));
        QVERIFY(QDir().mkpath(destination));

        writeFile(current + QStringLiteral("/source.txt"), "source");
        writeFile(current + QStringLiteral("/existing.txt"), "existing");

        MahoDirectoryModel model;
        openAndSettle(model, current);
        QTRY_VERIFY_WITH_TIMEOUT(findRow(model, QStringLiteral("source.txt")) >= 0, 5000);

        model.renameIndex(findRow(model, QStringLiteral("source.txt")), QStringLiteral("renamed.txt"));
        QTRY_COMPARE_WITH_TIMEOUT(model.operationMessage(), QStringLiteral("Renamed to renamed.txt"), 5000);
        QTRY_VERIFY_WITH_TIMEOUT(QFileInfo::exists(current + QStringLiteral("/renamed.txt")), 5000);

        QTRY_VERIFY_WITH_TIMEOUT(findRow(model, QStringLiteral("renamed.txt")) >= 0, 5000);
        model.renameIndex(findRow(model, QStringLiteral("renamed.txt")), QStringLiteral("existing.txt"));
        QCOMPARE(model.operationMessage(), QStringLiteral("An item named existing.txt already exists."));
        QVERIFY(QFileInfo::exists(current + QStringLiteral("/renamed.txt")));
        QCOMPARE(QFile(current + QStringLiteral("/existing.txt")).size(), 8);

        const QString staleSource = temp.filePath(QStringLiteral("stale.txt"));
        writeFile(staleSource, "stale");
        const QVariantList staleUrls = urls({dirUrl(staleSource)});
        QVERIFY(model.canDropUrlsTo(staleUrls, dirUrl(destination)));
        QVERIFY(QFile::remove(staleSource));
        QVERIFY(!model.canDropUrlsTo(staleUrls, dirUrl(destination)));
        model.dropUrls(staleUrls, dirUrl(destination), Qt::MoveAction);
        QCOMPARE(model.operationMessage(),
                 QStringLiteral("A source item is no longer available. Reload the source folder."));

        const QString staleDestination = temp.filePath(QStringLiteral("gone-destination"));
        QVERIFY(QDir().mkpath(staleDestination));
        writeFile(temp.filePath(QStringLiteral("fresh.txt")), "fresh");
        const QVariantList freshUrls = urls({dirUrl(temp.filePath(QStringLiteral("fresh.txt")))});
        QVERIFY(QDir().rmdir(staleDestination));
        QVERIFY(!model.canDropUrlsTo(freshUrls, dirUrl(staleDestination)));
        model.dropUrls(freshUrls, dirUrl(staleDestination), Qt::CopyAction);
        QCOMPARE(model.operationMessage(), QStringLiteral("The drop destination is not a folder."));
    }

    void clipboardPayloadCarriesFilesFoldersAndCutState()
    {
        QTemporaryDir temp;
        QVERIFY(temp.isValid());
        QVERIFY(QDir().mkpath(temp.filePath(QStringLiteral("folder"))));
        writeFile(temp.filePath(QStringLiteral("file.txt")), "payload");

        MahoDirectoryModel model;
        openAndSettle(model, temp.path());
        QTRY_VERIFY_WITH_TIMEOUT(findRow(model, QStringLiteral("file.txt")) >= 0, 5000);
        QTRY_VERIFY_WITH_TIMEOUT(findRow(model, QStringLiteral("folder")) >= 0, 5000);

        const QVariantList rows {
            findRow(model, QStringLiteral("file.txt")),
            findRow(model, QStringLiteral("folder")),
        };

        model.copyRows(rows, false);
        const QMimeData *copyMime = QApplication::clipboard()->mimeData();
        QVERIFY(copyMime);
        QCOMPARE(copyMime->urls().size(), 2);
        QVERIFY(copyMime->urls().contains(dirUrl(temp.filePath(QStringLiteral("file.txt")))));
        QVERIFY(copyMime->urls().contains(dirUrl(temp.filePath(QStringLiteral("folder")))));
        QCOMPARE(copyMime->data(QStringLiteral("application/x-kde-cutselection")), QByteArrayLiteral("0"));

        model.copyRows(rows, true);
        const QMimeData *cutMime = QApplication::clipboard()->mimeData();
        QVERIFY(cutMime);
        QCOMPARE(cutMime->urls().size(), 2);
        QCOMPARE(cutMime->data(QStringLiteral("application/x-kde-cutselection")), QByteArrayLiteral("1"));
    }

    void trashAndPermanentDeleteAreDistinct()
    {
        const QString trashBase =
            QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation)
            + QStringLiteral("/Trash");
        QVERIFY(QDir(trashBase).removeRecursively() || !QFileInfo::exists(trashBase));

        QTemporaryDir temp;
        QVERIFY(temp.isValid());
        writeFile(temp.filePath(QStringLiteral("trash-me.txt")), "trash");
        writeFile(temp.filePath(QStringLiteral("delete-me.txt")), "delete");

        MahoDirectoryModel model;
        openAndSettle(model, temp.path());
        QTRY_VERIFY_WITH_TIMEOUT(findRow(model, QStringLiteral("trash-me.txt")) >= 0, 5000);

        model.trashRows(QVariantList { findRow(model, QStringLiteral("trash-me.txt")) });
        QTRY_VERIFY_WITH_TIMEOUT(!QFileInfo::exists(temp.filePath(QStringLiteral("trash-me.txt"))), 5000);
        QTRY_VERIFY_WITH_TIMEOUT(model.operationMessage().contains(QStringLiteral("Trash")), 5000);

        const QString trashRoot = trashBase + QStringLiteral("/files");
        QTRY_VERIFY_WITH_TIMEOUT(QFileInfo::exists(trashRoot + QStringLiteral("/trash-me.txt")), 5000);

        QTRY_VERIFY_WITH_TIMEOUT(findRow(model, QStringLiteral("delete-me.txt")) >= 0, 5000);
        model.deleteRows(QVariantList { findRow(model, QStringLiteral("delete-me.txt")) });
        QTRY_COMPARE_WITH_TIMEOUT(
            model.operationMessage(),
            QStringLiteral("Permanently deleted delete-me.txt"),
            5000);
        QTRY_VERIFY_WITH_TIMEOUT(!QFileInfo::exists(temp.filePath(QStringLiteral("delete-me.txt"))), 5000);
        QVERIFY(!QFileInfo::exists(trashRoot + QStringLiteral("/delete-me.txt")));
    }

    void duplicatesMultipleSelectedItemsWithoutOverwrite()
    {
        QTemporaryDir temp;
        QVERIFY(temp.isValid());
        writeFile(temp.filePath(QStringLiteral("one.txt")), "one");
        writeFile(temp.filePath(QStringLiteral("two.txt")), "two");

        MahoDirectoryModel model;
        openAndSettle(model, temp.path());
        QTRY_VERIFY_WITH_TIMEOUT(findRow(model, QStringLiteral("one.txt")) >= 0, 5000);
        QTRY_VERIFY_WITH_TIMEOUT(findRow(model, QStringLiteral("two.txt")) >= 0, 5000);

        const int before = QDir(temp.path()).entryList(
            QDir::Files | QDir::NoDotAndDotDot).size();
        model.duplicateRows(QVariantList {
            findRow(model, QStringLiteral("one.txt")),
            findRow(model, QStringLiteral("two.txt")),
        });
        QTRY_COMPARE_WITH_TIMEOUT(model.operationMessage(), QStringLiteral("Duplicated 2 items"), 5000);
        QTRY_COMPARE_WITH_TIMEOUT(
            QDir(temp.path()).entryList(QDir::Files | QDir::NoDotAndDotDot).size(),
            before + 2,
            5000);
        QCOMPARE(QFile(temp.filePath(QStringLiteral("one.txt"))).size(), 3);
        QCOMPARE(QFile(temp.filePath(QStringLiteral("two.txt"))).size(), 3);
    }

    void sortingAndPropertiesAreTruthful()
    {
        QTemporaryDir temp;
        QVERIFY(temp.isValid());
        writeFile(temp.filePath(QStringLiteral("small.txt")), "x");
        writeFile(temp.filePath(QStringLiteral("large.txt")), "123456789");
        QVERIFY(QDir().mkpath(temp.filePath(QStringLiteral("folder"))));
        writeFile(temp.filePath(QStringLiteral("folder/inside.txt")), "contents");

        MahoDirectoryModel model;
        openAndSettle(model, temp.path());
        QTRY_VERIFY_WITH_TIMEOUT(findRow(model, QStringLiteral("small.txt")) >= 0, 5000);

        model.setSortKey(QStringLiteral("size"));
        model.setSortDescending(true);
        const int largeRow = findRow(model, QStringLiteral("large.txt"));
        const int smallRow = findRow(model, QStringLiteral("small.txt"));
        QVERIFY(largeRow >= 0);
        QVERIFY(smallRow >= 0);
        QVERIFY(largeRow < smallRow);

        const QString fileDetails = model.propertiesText(largeRow);
        QVERIFY(fileDetails.contains(QStringLiteral("Name: large.txt")));
        QVERIFY(fileDetails.contains(QStringLiteral("Type:")));
        QVERIFY(fileDetails.contains(QStringLiteral("MIME:")));
        QVERIFY(fileDetails.contains(QStringLiteral("Size:")));
        QVERIFY(fileDetails.contains(QStringLiteral("Modified:")));
        QVERIFY(fileDetails.contains(QStringLiteral("Location:")));

        QSignalSpy propertiesSpy(&model, &MahoDirectoryModel::propertiesReady);
        model.requestProperties(findRow(model, QStringLiteral("folder")));
        QTRY_VERIFY_WITH_TIMEOUT(propertiesSpy.count() >= 2, 5000);
        const QList<QVariant> finalProperties = propertiesSpy.at(propertiesSpy.count() - 1);
        const QString folderDetails = finalProperties.at(0).toString();
        QVERIFY(folderDetails.contains(QStringLiteral("Size:")));
        QVERIFY(!folderDetails.contains(QStringLiteral("Calculating")));
        QVERIFY(folderDetails.contains(QStringLiteral("Contents: 1 file")));
    }

    void staleCurrentDirectoryFailsMutations()
    {
        QTemporaryDir temp;
        QVERIFY(temp.isValid());

        const QString current = temp.filePath(QStringLiteral("stale-current"));
        QVERIFY(QDir().mkpath(current));

        MahoDirectoryModel model;
        openAndSettle(model, current);
        QVERIFY(model.canMutateCurrentDirectory());

        QVERIFY(QDir().rmdir(current));
        QVERIFY(!model.canMutateCurrentDirectory());
        model.createFile(QStringLiteral("blocked.txt"));
        QCOMPARE(model.operationMessage(), QStringLiteral("Create items from a writable local folder."));
        QVERIFY(!QFileInfo::exists(current + QStringLiteral("/blocked.txt")));
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
