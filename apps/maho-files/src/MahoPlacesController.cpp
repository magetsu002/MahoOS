#include "MahoPlacesController.h"

#include "MahoDirectoryModel.h"

#include <KFilePlacesModel>

MahoPlacesController::MahoPlacesController(KFilePlacesModel *placesModel,
                                           MahoDirectoryModel *directoryModel,
                                           QObject *parent)
    : QObject(parent)
    , m_placesModel(placesModel)
    , m_directoryModel(directoryModel)
{
    Q_ASSERT(m_placesModel);
    Q_ASSERT(m_directoryModel);

    connect(m_placesModel, &KFilePlacesModel::setupDone, this,
            [this](const QModelIndex &index, bool success) {
        if (!m_pendingSetup.isValid() || index != m_pendingSetup)
            return;

        const QPersistentModelIndex pending = m_pendingSetup;
        m_pendingSetup = QPersistentModelIndex();
        setBusyRow(-1);

        if (!success) {
            if (m_errorString.isEmpty())
                setErrorString(QStringLiteral("Could not mount this device."));
            return;
        }

        openIndex(pending);
    });

    connect(m_placesModel, &KFilePlacesModel::teardownDone, this,
            [this](const QModelIndex &index, Solid::ErrorType error, const QVariant &) {
        if (index.row() == m_busyRow)
            setBusyRow(-1);
        if (error != Solid::NoError && m_errorString.isEmpty())
            setErrorString(QStringLiteral("Could not unmount this device."));
    });

    connect(m_placesModel, &KFilePlacesModel::errorMessage, this,
            [this](const QString &message) {
        setBusyRow(-1);
        setErrorString(message);
    });
}

int MahoPlacesController::busyRow() const
{
    return m_busyRow;
}

QString MahoPlacesController::errorString() const
{
    return m_errorString;
}

void MahoPlacesController::activate(int row)
{
    if (!m_placesModel)
        return;

    const QModelIndex index = m_placesModel->index(row, 0);
    if (!index.isValid())
        return;

    setErrorString({});

    if (m_placesModel->setupNeeded(index)) {
        m_pendingSetup = QPersistentModelIndex(index);
        setBusyRow(row);
        m_placesModel->requestSetup(index);
        return;
    }

    openIndex(index);
}

bool MahoPlacesController::canEject(int row) const
{
    if (!m_placesModel)
        return false;
    const QModelIndex index = m_placesModel->index(row, 0);
    return index.isValid() && index.data(KFilePlacesModel::EjectAllowedRole).toBool();
}

bool MahoPlacesController::canTeardown(int row) const
{
    if (!m_placesModel)
        return false;
    const QModelIndex index = m_placesModel->index(row, 0);
    return index.isValid() && m_placesModel->isTeardownAllowed(index);
}

void MahoPlacesController::eject(int row)
{
    if (!m_placesModel)
        return;
    const QModelIndex index = m_placesModel->index(row, 0);
    if (!index.isValid() || !canEject(row))
        return;
    setErrorString({});
    setBusyRow(row);
    m_placesModel->requestEject(index);
}

void MahoPlacesController::teardown(int row)
{
    if (!m_placesModel)
        return;
    const QModelIndex index = m_placesModel->index(row, 0);
    if (!index.isValid() || !canTeardown(row))
        return;
    setErrorString({});
    setBusyRow(row);
    m_placesModel->requestTeardown(index);
}

void MahoPlacesController::setBusyRow(int row)
{
    if (m_busyRow == row)
        return;
    m_busyRow = row;
    emit busyRowChanged();
}

void MahoPlacesController::setErrorString(const QString &error)
{
    if (m_errorString == error)
        return;
    m_errorString = error;
    emit errorStringChanged();
}

void MahoPlacesController::openIndex(const QModelIndex &index)
{
    if (!index.isValid())
        return;

    const QUrl url = m_placesModel->url(index);
    if (!url.isValid() || url.isEmpty()) {
        setErrorString(QStringLiteral("This place is not available yet."));
        return;
    }

    m_directoryModel->openUrl(url);
}
