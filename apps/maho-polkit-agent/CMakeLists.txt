cmake_minimum_required(VERSION 3.25)

project(MahoPolkitAgent VERSION 0.1.0 LANGUAGES C)

include(GNUInstallDirs)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

find_package(PkgConfig REQUIRED)
pkg_check_modules(GTK4 REQUIRED IMPORTED_TARGET gtk4)
pkg_check_modules(POLKIT_AGENT REQUIRED IMPORTED_TARGET polkit-agent-1)
pkg_check_modules(POLKIT_GOBJECT REQUIRED IMPORTED_TARGET polkit-gobject-1)

add_executable(maho-polkit-agent
    src/main.c
)

target_compile_definitions(maho-polkit-agent PRIVATE
    POLKIT_AGENT_I_KNOW_API_IS_SUBJECT_TO_CHANGE
)

target_compile_options(maho-polkit-agent PRIVATE
    -Wall -Wextra -Wpedantic -Werror
)

target_link_libraries(maho-polkit-agent PRIVATE
    PkgConfig::GTK4
    PkgConfig::POLKIT_AGENT
    PkgConfig::POLKIT_GOBJECT
)

install(TARGETS maho-polkit-agent
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)
