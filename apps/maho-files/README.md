# Maho Files

Maho Files is the native file manager for MahoOS. The interface is built with Qt
Quick while KDE Frameworks/KIO provides file listing, metadata, navigation, and
file operations.

## Features

- local and KIO URL navigation
- back, forward, up, and home navigation
- live directory updates
- KDE places and device entries
- file and folder icons from the desktop theme
- hidden-file toggle
- recursive search from the current location
- create folder
- rename
- move to trash
- copy, cut, and paste
- native file drag-out
- wallpaper-derived Maho colors

File operations go through KIO rather than a parallel filesystem implementation.

## Source

```text
qml/    Interface
src/    Qt/KIO models and controllers
```
