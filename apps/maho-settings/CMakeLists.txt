cmake_minimum_required(VERSION 3.25)

project(MahoSettings VERSION 0.1.0 LANGUAGES CXX)

include(GNUInstallDirs)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Qt6 6.8 REQUIRED COMPONENTS Core Gui Qml Quick QuickControls2)
find_package(Python3 REQUIRED COMPONENTS Interpreter)

qt_standard_project_setup(REQUIRES 6.8)

qt_add_executable(maho-settings
    src/main.cpp
    src/MahoPalette.cpp
    src/MahoPalette.h
    src/MahoSettingsBridge.cpp
    src/MahoSettingsBridge.h
)

qt_add_qml_module(maho-settings
    URI Maho.Settings
    VERSION 1.0
    QML_FILES
        qml/Main.qml
        qml/components/ChoicePill.qml
        qml/components/AppearanceRow.qml
        qml/components/MahoSegmentedControl.qml
        qml/components/MahoComboBox.qml
        qml/components/MahoIcon.qml
        qml/components/MahoInsetRow.qml
        qml/components/ManagedListRow.qml
        qml/components/MahoSectionLabel.qml
        qml/components/MahoScrollBar.qml
        qml/components/MahoSettingsTheme.qml
        qml/components/MahoSidebarItem.qml
        qml/components/MahoTextArea.qml
        qml/components/MahoTextField.qml
        qml/components/MahoSlider.qml
        qml/components/MahoSwitch.qml
        qml/components/PageHeader.qml
        qml/components/SettingCard.qml
        qml/components/SettingsSidebar.qml
        qml/components/StatePanel.qml
        qml/pages/AboutPage.qml
        qml/pages/AppearancePage.qml
        qml/pages/ApplicationsPage.qml
        qml/pages/ConfigurationPage.qml
        qml/pages/DiagnosticsPage.qml
        qml/pages/DeferredPage.qml
        qml/pages/DisplaysPage.qml
        qml/pages/InputPage.qml
        qml/pages/NotificationsPage.qml
        qml/pages/PowerPage.qml
        qml/pages/RegionPage.qml
        qml/pages/ShortcutsPage.qml
        qml/pages/RulesPage.qml
        qml/pages/MotionPage.qml
        qml/pages/SessionPage.qml
        qml/pages/SoundPage.qml
)

execute_process(
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/source-fingerprint.py" "${CMAKE_CURRENT_SOURCE_DIR}"
    RESULT_VARIABLE MAHO_SETTINGS_FINGERPRINT_RESULT
    OUTPUT_VARIABLE MAHO_SETTINGS_SOURCE_FINGERPRINT
    OUTPUT_STRIP_TRAILING_WHITESPACE
)
string(LENGTH "${MAHO_SETTINGS_SOURCE_FINGERPRINT}" MAHO_SETTINGS_FINGERPRINT_LENGTH)
if(NOT MAHO_SETTINGS_FINGERPRINT_RESULT EQUAL 0 OR
   NOT MAHO_SETTINGS_SOURCE_FINGERPRINT MATCHES "^[0-9a-f]+$" OR
   NOT MAHO_SETTINGS_FINGERPRINT_LENGTH EQUAL 64)
    message(FATAL_ERROR "Unable to compute Maho Settings source fingerprint")
endif()

target_compile_definitions(maho-settings PRIVATE
    MAHO_SETTINGS_SOURCE_FINGERPRINT="${MAHO_SETTINGS_SOURCE_FINGERPRINT}"
)

target_include_directories(maho-settings PRIVATE src)

target_link_libraries(maho-settings PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::Qml
    Qt6::Quick
    Qt6::QuickControls2
)

install(TARGETS maho-settings
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)

install(FILES io.maho.Settings.desktop
    DESTINATION ${CMAKE_INSTALL_DATADIR}/applications
)

install(FILES io.maho.Settings.Session.desktop
    DESTINATION ${CMAKE_INSTALL_SYSCONFDIR}/xdg/autostart
)
