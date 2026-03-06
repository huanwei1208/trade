# cmake/submodule_check.cmake
#
# Provides trade_ensure_submodules():
#   Checks each vendor/* sentinel file. If any is missing, runs
#   `git submodule update --init --recursive` to pull everything.
#
# Call this BEFORE any add_subdirectory(vendor/...) in CMakeLists.txt.

function(trade_ensure_submodules)
    find_package(Git QUIET)

    if(NOT GIT_FOUND)
        message(WARNING "[submodules] git not found – skipping auto-init.")
        return()
    endif()

    if(NOT EXISTS "${PROJECT_SOURCE_DIR}/.git")
        return()  # exported tree / CI archive – nothing to do
    endif()

    # One sentinel per registered submodule.
    # A missing file means the submodule was never cloned.
    set(_sentinels
        "${CMAKE_CURRENT_SOURCE_DIR}/vendor/duckdb/CMakeLists.txt"
        "${CMAKE_CURRENT_SOURCE_DIR}/vendor/lightgbm/CMakeLists.txt"
        "${CMAKE_CURRENT_SOURCE_DIR}/vendor/spdlog/CMakeLists.txt"
        "${CMAKE_CURRENT_SOURCE_DIR}/vendor/fmt/CMakeLists.txt"
        "${CMAKE_CURRENT_SOURCE_DIR}/vendor/nlohmann_json/CMakeLists.txt"
        "${CMAKE_CURRENT_SOURCE_DIR}/vendor/yaml-cpp/CMakeLists.txt"
        "${CMAKE_CURRENT_SOURCE_DIR}/vendor/pugixml/CMakeLists.txt"
        "${CMAKE_CURRENT_SOURCE_DIR}/vendor/cpp-httplib/httplib.h"
        "${CMAKE_CURRENT_SOURCE_DIR}/vendor/googletest/CMakeLists.txt"
        "${CMAKE_CURRENT_SOURCE_DIR}/vendor/eigen/CMakeLists.txt"
        "${CMAKE_CURRENT_SOURCE_DIR}/vendor/abseil-cpp/CMakeLists.txt"
        "${CMAKE_CURRENT_SOURCE_DIR}/vendor/re2/CMakeLists.txt"
        "${CMAKE_CURRENT_SOURCE_DIR}/vendor/curl/CMakeLists.txt"
        "${CMAKE_CURRENT_SOURCE_DIR}/vendor/arrow/cpp/CMakeLists.txt"
    )

    set(_needs_init FALSE)
    foreach(_f IN LISTS _sentinels)
        if(NOT EXISTS "${_f}")
            message(STATUS "[submodules] not yet cloned: ${_f}")
            set(_needs_init TRUE)
            break()
        endif()
    endforeach()

    if(_needs_init)
        message(STATUS "[submodules] Running: git submodule update --init --recursive")
        execute_process(
            COMMAND "${GIT_EXECUTABLE}" submodule update --init --recursive
            WORKING_DIRECTORY "${PROJECT_SOURCE_DIR}"
            RESULT_VARIABLE _rc
        )
        if(NOT _rc EQUAL 0)
            message(WARNING
                "[submodules] git submodule update --init --recursive failed "
                "(exit ${_rc}). Run it manually, then re-run cmake.")
        else()
            message(STATUS "[submodules] Submodules initialised successfully.")
        endif()
    endif()
endfunction()
