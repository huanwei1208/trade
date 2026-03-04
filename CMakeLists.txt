cmake_minimum_required(VERSION 3.25)
project(trade VERSION 0.1.0 LANGUAGES CXX C)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Apple Clang searches /usr/local/include (built-in) before -isystem dirs.
# Use -I (not -isystem) for imported targets so Homebrew headers win.
set(CMAKE_NO_SYSTEM_FROM_IMPORTED ON)

# Options
option(BUILD_TESTING "Build tests" ON)
option(BUILD_PYTHON_BINDINGS "Build nanobind Python bindings" OFF)

# ── Git submodule auto-init ───────────────────────────────────────────────────
include(cmake/submodule_check.cmake)
trade_ensure_submodules()

# ── Dependencies (vendor submodules → system package fallback) ────────────────
include(cmake/deps.cmake)

# Core library sources
include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/trade_core_sources.cmake)

if(HAVE_ONNXRUNTIME)
    list(APPEND TRADE_SENTIMENT_SOURCES src/sentiment/onnx_sentiment.cpp)
endif()

add_library(trade_deps INTERFACE)
target_link_libraries(trade_deps INTERFACE
    Arrow::arrow_shared
    Parquet::parquet_shared
    SQLite::SQLite3
    Eigen3::Eigen
    spdlog::spdlog
    nlohmann_json::nlohmann_json
    httplib::httplib
    fmt::fmt
    yaml-cpp::yaml-cpp
    pugixml::pugixml
    CURL::libcurl
    re2::re2
    OpenSSL::Crypto
    # DuckDB has a circular symbol dependency between duckdb_static and the
    # extension loader / extension libs: duckdb_static references LoadAllExtensions
    # which is defined in duckdb_generated_extension_loader, yet CMake places the
    # extension libs before duckdb_static in link order.  Use --start-group /
    # --end-group (RESCAN) so GNU ld makes multiple passes until all refs resolve.
    $<LINK_GROUP:RESCAN,duckdb_static,duckdb_generated_extension_loader,parquet_extension,core_functions_extension,jemalloc_extension>
)
target_include_directories(trade_deps INTERFACE
    ${CMAKE_CURRENT_SOURCE_DIR}/vendor/duckdb/src/include
)

if(HAVE_LIGHTGBM)
    target_link_libraries(trade_deps INTERFACE LightGBM::lightgbm)
endif()

if(HAVE_ONNXRUNTIME)
    target_link_libraries(trade_deps INTERFACE onnxruntime::onnxruntime)
endif()

function(trade_add_object_module MODULE_NAME)
    add_library(${MODULE_NAME} OBJECT ${ARGN})
    target_include_directories(${MODULE_NAME} PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/include
    )
    target_link_libraries(${MODULE_NAME} PRIVATE trade_deps)
endfunction()

trade_add_object_module(trade_obj_base ${TRADE_BASE_SOURCES})
trade_add_object_module(trade_obj_data ${TRADE_DATA_SOURCES})
trade_add_object_module(trade_obj_feature ${TRADE_FEATURE_SOURCES})
trade_add_object_module(trade_obj_stats ${TRADE_STATS_SOURCES})
trade_add_object_module(trade_obj_ml ${TRADE_ML_SOURCES})
trade_add_object_module(trade_obj_risk ${TRADE_RISK_SOURCES})
trade_add_object_module(trade_obj_regime ${TRADE_REGIME_SOURCES})
trade_add_object_module(trade_obj_backtest ${TRADE_BACKTEST_SOURCES})
trade_add_object_module(trade_obj_sentiment ${TRADE_SENTIMENT_SOURCES})
trade_add_object_module(trade_obj_decision ${TRADE_DECISION_SOURCES})
trade_add_object_module(trade_obj_signal ${TRADE_SIGNAL_SOURCES})
trade_add_object_module(trade_obj_app ${TRADE_APP_SOURCES})

# Collect all headers for IDE visibility (CLion / VS Code).
# CONFIGURE_DEPENDS re-runs cmake when new .h files are added.
# These files are NOT compiled — they're metadata for the IDE project tree.
file(GLOB_RECURSE TRADE_HEADERS CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/include/trade/*.h"
)

# Organise headers into virtual folders mirroring include/trade/<module>/
foreach(_hdr IN LISTS TRADE_HEADERS)
    # Strip the include/ prefix to get the relative path
    file(RELATIVE_PATH _rel "${CMAKE_CURRENT_SOURCE_DIR}/include" "${_hdr}")
    # Take the first directory component as the group name
    get_filename_component(_grp "${_rel}" DIRECTORY)
    source_group("Headers\\${_grp}" FILES "${_hdr}")
endforeach()

add_library(trade_core STATIC
    ${TRADE_HEADERS}                           # IDE visibility only
    $<TARGET_OBJECTS:trade_obj_base>
    $<TARGET_OBJECTS:trade_obj_data>
    $<TARGET_OBJECTS:trade_obj_feature>
    $<TARGET_OBJECTS:trade_obj_stats>
    $<TARGET_OBJECTS:trade_obj_ml>
    $<TARGET_OBJECTS:trade_obj_risk>
    $<TARGET_OBJECTS:trade_obj_regime>
    $<TARGET_OBJECTS:trade_obj_backtest>
    $<TARGET_OBJECTS:trade_obj_sentiment>
    $<TARGET_OBJECTS:trade_obj_decision>
    $<TARGET_OBJECTS:trade_obj_signal>
    $<TARGET_OBJECTS:trade_obj_app>
)

target_include_directories(trade_core PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
)
target_link_libraries(trade_core PUBLIC trade_deps)

# Output layout
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)

# CLI tool
include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/trade_cli_sources.cmake)
add_executable(trade_cli ${TRADE_CLI_SOURCES})
target_link_libraries(trade_cli PRIVATE trade_core)
target_compile_definitions(trade_cli PRIVATE
    TRADE_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}")

if(UNIX)
    find_library(READLINE_LIB readline)
    if(READLINE_LIB)
        target_link_libraries(trade_cli PRIVATE ${READLINE_LIB})
        target_compile_definitions(trade_cli PRIVATE TRADE_HAS_READLINE=1)
    endif()
endif()

# Symlinks in build dir
file(CREATE_LINK ${CMAKE_CURRENT_SOURCE_DIR}/config
     ${CMAKE_BINARY_DIR}/config SYMBOLIC)
file(CREATE_LINK ${CMAKE_CURRENT_SOURCE_DIR}/data
     ${CMAKE_BINARY_DIR}/data SYMBOLIC)

# Tests
if(BUILD_TESTING)
    enable_testing()
    include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/tests.cmake)
    trade_configure_tests()
endif()

# Python bindings
if(BUILD_PYTHON_BINDINGS)
    include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/python_bindings.cmake)
    trade_configure_python_bindings()
endif()
