cmake_minimum_required(VERSION 3.25)

project(MahoFiles VERSION 0.1.0 LANGUAGES CXX)

include(GNUInstallDirs)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Qt6 6.8 REQUIRED COMPONENTS Core Gui Widgets Qml Quick QuickControls2)
find_package(Python3 REQUIRED COMPONENTS Interpreter)
# Arch's kio package installs /usr/lib/cmake/KF6KIO/KF6KIOConfig.cmake.
# Consume that package directly instead of depending on ECM's umbrella FindKF6.
find_package(KF6KIO CONFIG REQUIRED)
find_package(KF6Service CONFIG REQUIRED)

qt_standard_project_setup(REQUIRES 6.8)

option(MAHO_FILES_BUILD_TESTS "Build focused Maho Files model tests" OFF)

qt_add_executable(maho-files
    src/main.cpp
    src/MahoDirectoryModel.cpp
    src/MahoDirectoryModel.h
    src/MahoPalette.cpp
    src/MahoPalette.h
    src/MahoPlacesController.cpp
    src/MahoPlacesController.h
)

qt_add_qml_module(maho-files
    URI Maho.Files
    VERSION 1.0
    QML_FILES
        qml/Main.qml
        qml/MahoScrollBar.qml
)

execute_process(
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/source-fingerprint.py" "${CMAKE_CURRENT_SOURCE_DIR}"
    RESULT_VARIABLE MAHO_FILES_FINGERPRINT_RESULT
    OUTPUT_VARIABLE MAHO_FILES_SOURCE_FINGERPRINT
    OUTPUT_STRIP_TRAILING_WHITESPACE
)
string(LENGTH "${MAHO_FILES_SOURCE_FINGERPRINT}" MAHO_FILES_FINGERPRINT_LENGTH)
if(NOT MAHO_FILES_FINGERPRINT_RESULT EQUAL 0 OR
   NOT MAHO_FILES_SOURCE_FINGERPRINT MATCHES "^[0-9a-f]+$" OR
   NOT MAHO_FILES_FINGERPRINT_LENGTH EQUAL 64)
    message(FATAL_ERROR "Unable to compute Maho Files source fingerprint")
endif()

target_compile_definitions(maho-files PRIVATE
    MAHO_FILES_SOURCE_FINGERPRINT="${MAHO_FILES_SOURCE_FINGERPRINT}"
)

target_include_directories(maho-files PRIVATE src)

target_link_libraries(maho-files PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::Widgets
    Qt6::Qml
    Qt6::Quick
    Qt6::QuickControls2
    KF6::KIOCore
    KF6::KIOGui
    KF6::KIOFileWidgets
    KF6::Service
)


if(MAHO_FILES_BUILD_TESTS)
    find_package(Qt6 6.8 REQUIRED COMPONENTS Test)

    qt_add_executable(maho-files-model-tests
        tests/MahoDirectoryModelTest.cpp
        src/MahoDirectoryModel.cpp
        src/MahoDirectoryModel.h
    )
    target_include_directories(maho-files-model-tests PRIVATE src)
    target_link_libraries(maho-files-model-tests PRIVATE
        Qt6::Core
        Qt6::Gui
        Qt6::Widgets
        Qt6::Quick
        Qt6::Test
        KF6::KIOCore
        KF6::KIOGui
        KF6::KIOFileWidgets
        KF6::Service
    )

    enable_testing()
    file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/test-home")
    file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/test-xdg-data")
    add_test(NAME maho-files-model-ops COMMAND maho-files-model-tests)
    set_tests_properties(maho-files-model-ops PROPERTIES
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen;HOME=${CMAKE_CURRENT_BINARY_DIR}/test-home;XDG_DATA_HOME=${CMAKE_CURRENT_BINARY_DIR}/test-xdg-data"
    )
endif()

install(TARGETS maho-files
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)

install(FILES io.maho.Files.desktop
    DESTINATION ${CMAKE_INSTALL_DATADIR}/applications
)
