import QtQuick
import Quickshell

QtObject {
    readonly property string homeDir: Quickshell.env("HOME")
    readonly property string configuredWallpaperDir:
        Quickshell.env("QS_WALLPAPER_DIR")
    readonly property string configuredCacheHome:
        Quickshell.env("XDG_CACHE_HOME")

    property string wallpaperDir:
        configuredWallpaperDir !== ""
            ? configuredWallpaperDir
            : homeDir + "/Wallpapers"
    readonly property string cacheHome:
        configuredCacheHome !== ""
            ? configuredCacheHome
            : homeDir + "/.cache"
    readonly property string cacheDir: cacheHome + "/maho/themes"
    readonly property string thumbDir: cacheDir + "/thumbs"

    property bool uiAnimationsEnabled: true
    property real uiAnimationScale: 1.0
    property string wallpaperTransitionType: "random"
    property real wallpaperTransitionDuration: 0.6
    property int wallpaperTransitionFps: 60
    property int closeDelayMs: 120
    property int scrollThrottleMs: 150
    property int filterAnimationMs: 800
    property int itemAnimationMs: 500
    property string themeMode:
        Quickshell.env("MAHO_THEME_MODE") === "light" ? "light" : "dark"
}
