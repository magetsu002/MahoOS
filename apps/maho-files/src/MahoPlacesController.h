#pragma once

#include <QObject>
#include <QPersistentModelIndex>

class KFilePlacesModel;
class MahoDirectoryModel;

class MahoPlacesController final : public QObject
{
    Q_OBJECT
    Q_PROPERTY(int busyRow READ busyRow NOTIFY busyRowChanged)
    Q_PROPERTY(QString errorString READ errorString NOTIFY errorStringChanged)

public:
    explicit MahoPlacesController(KFilePlacesModel *placesModel,
                                  MahoDirectoryModel *directoryModel,
                                  QObject *parent = nullptr);

    int busyRow() const;
    QString errorString() const;

    Q_INVOKABLE void activate(int row);
    Q_INVOKABLE bool canEject(int row) const;
    Q_INVOKABLE bool canTeardown(int row) const;
    Q_INVOKABLE void eject(int row);
    Q_INVOKABLE void teardown(int row);

signals:
    void busyRowChanged();
    void errorStringChanged();

private:
    void setBusyRow(int row);
    void setErrorString(const QString &error);
    void openIndex(const QModelIndex &index);

    KFilePlacesModel *m_placesModel = nullptr;
    MahoDirectoryModel *m_directoryModel = nullptr;
    QPersistentModelIndex m_pendingSetup;
    int m_busyRow = -1;
    QString m_errorString;
};
