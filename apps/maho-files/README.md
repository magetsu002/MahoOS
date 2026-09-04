# Maho Files

Maho Files is a native Qt/QML file-management frontend for MahoOS. The visible application is owned by Maho; mature file semantics come from KDE Frameworks/KIO.

## M0 boundary

Implemented now:

- `KCoreDirLister` directory listing and live updates
- `KFileItem` metadata and icon identity
- `KFilePlacesModel` places/devices source
- native Qt Quick shell and Palette V2 bridge
- local and KIO URL navigation
- standard desktop-file opening through Qt

Intentionally not implemented in M0:

- copy/move/rename/trash/create-folder actions
- search
- tabs/split view
- thumbnails/preview jobs
- device mount/eject controls
- default-file-manager or Dock/Launcher routing

Those features must be added by calling the appropriate KIO/KFilePlacesModel APIs rather than implementing parallel filesystem semantics.
