cmake_minimum_required(VERSION 3.25)

project(MahoFiles VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Qt6 6.8 REQUIRED COMPONENTS Core Gui Qml Quick QuickControls2)
# Arch's kio package installs /usr/lib/cmake/KF6KIO/KF6KIOConfig.cmake.
# Consume that package directly instead of depending on ECM's umbrella FindKF6.
find_package(KF6KIO CONFIG REQUIRED)

qt_standard_project_setup(REQUIRES 6.8)

qt_add_executable(maho-files
    src/main.cpp
    src/MahoDirectoryModel.cpp
    src/MahoDirectoryModel.h
    src/MahoPalette.cpp
    src/MahoPalette.h
)

qt_add_qml_module(maho-files
    URI Maho.Files
    VERSION 1.0
    QML_FILES
        qml/Main.qml
)

target_include_directories(maho-files PRIVATE src)

target_link_libraries(maho-files PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::Qml
    Qt6::Quick
    Qt6::QuickControls2
    KF6::KIOCore
    KF6::KIOFileWidgets
)

install(TARGETS maho-files
    RUNTIME DESTINATION bin
)
