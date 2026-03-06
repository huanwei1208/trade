# cmake/deps.cmake
#
# All third-party dependency resolution for the trade project.
#
# Resolution order for each library:
#   1. vendor/<lib>  – git submodule (preferred, reproducible)
#   2. system        – find_package / find_library fallback
#
# System-only (security-sensitive / no practical standalone build):
#   OpenSSL, ONNX Runtime

# ── DuckDB ───────────────────────────────────────────────────────────────────
# Always from vendor submodule – embedded SQL analytics engine.
set(BUILD_UNITTESTS            OFF CACHE BOOL "" FORCE)
set(BUILD_BENCHMARKS           OFF CACHE BOOL "" FORCE)
set(DUCKDB_BUILD_BENCHMARKS    OFF CACHE BOOL "" FORCE)
add_subdirectory(vendor/duckdb EXCLUDE_FROM_ALL)

# ── fmt ──────────────────────────────────────────────────────────────────────
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/fmt/CMakeLists.txt")
    set(FMT_INSTALL OFF CACHE BOOL "" FORCE)
    add_subdirectory(vendor/fmt EXCLUDE_FROM_ALL)
    message(STATUS "fmt: vendor submodule")
else()
    find_package(fmt CONFIG REQUIRED)
    message(STATUS "fmt: system package")
endif()

# ── spdlog ───────────────────────────────────────────────────────────────────
# Must come after fmt so SPDLOG_FMT_EXTERNAL can find fmt::fmt.
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/spdlog/CMakeLists.txt")
    set(SPDLOG_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
    set(SPDLOG_BUILD_TESTS    OFF CACHE BOOL "" FORCE)
    set(SPDLOG_INSTALL        OFF CACHE BOOL "" FORCE)
    set(SPDLOG_FMT_EXTERNAL   ON  CACHE BOOL "" FORCE)
    add_subdirectory(vendor/spdlog EXCLUDE_FROM_ALL)
    message(STATUS "spdlog: vendor submodule")
else()
    find_package(spdlog CONFIG REQUIRED)
    message(STATUS "spdlog: system package")
endif()

# ── nlohmann_json ────────────────────────────────────────────────────────────
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/nlohmann_json/CMakeLists.txt")
    set(JSON_BuildTests OFF CACHE BOOL "" FORCE)
    set(JSON_Install    OFF CACHE BOOL "" FORCE)
    add_subdirectory(vendor/nlohmann_json EXCLUDE_FROM_ALL)
    message(STATUS "nlohmann_json: vendor submodule")
else()
    find_package(nlohmann_json CONFIG REQUIRED)
    message(STATUS "nlohmann_json: system package")
endif()

# ── yaml-cpp ─────────────────────────────────────────────────────────────────
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/yaml-cpp/CMakeLists.txt")
    set(YAML_CPP_BUILD_TESTS  OFF CACHE BOOL "" FORCE)
    set(YAML_CPP_BUILD_TOOLS  OFF CACHE BOOL "" FORCE)
    set(YAML_CPP_INSTALL      OFF CACHE BOOL "" FORCE)
    add_subdirectory(vendor/yaml-cpp EXCLUDE_FROM_ALL)
    message(STATUS "yaml-cpp: vendor submodule")
else()
    find_package(yaml-cpp CONFIG REQUIRED)
    message(STATUS "yaml-cpp: system package")
endif()

# ── pugixml ──────────────────────────────────────────────────────────────────
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/pugixml/CMakeLists.txt")
    add_subdirectory(vendor/pugixml EXCLUDE_FROM_ALL)
    message(STATUS "pugixml: vendor submodule")
else()
    find_package(pugixml CONFIG REQUIRED)
    message(STATUS "pugixml: system package")
endif()

# ── cpp-httplib ───────────────────────────────────────────────────────────────
# Header-only; HTTPLIB_COMPILE=OFF keeps it that way.
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/cpp-httplib/httplib.h")
    set(HTTPLIB_COMPILE                  OFF CACHE BOOL "" FORCE)
    set(HTTPLIB_USE_OPENSSL_IF_AVAILABLE OFF CACHE BOOL "" FORCE)
    if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/cpp-httplib/CMakeLists.txt")
        add_subdirectory(vendor/cpp-httplib EXCLUDE_FROM_ALL)
    else()
        # Older releases ship only the header; create a minimal interface target.
        add_library(httplib INTERFACE)
        target_include_directories(httplib INTERFACE
            "${CMAKE_CURRENT_SOURCE_DIR}/vendor/cpp-httplib")
        add_library(httplib::httplib ALIAS httplib)
    endif()
    # Ensure the namespaced alias always exists.
    if(TARGET httplib AND NOT TARGET httplib::httplib)
        add_library(httplib::httplib ALIAS httplib)
    endif()
    message(STATUS "cpp-httplib: vendor submodule")
else()
    find_package(httplib CONFIG REQUIRED)
    message(STATUS "cpp-httplib: system package")
endif()

# ── LightGBM (optional) ──────────────────────────────────────────────────────
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/lightgbm/CMakeLists.txt")
    set(BUILD_CLI  OFF CACHE BOOL "" FORCE)
    set(USE_MPI    OFF CACHE BOOL "" FORCE)
    set(USE_GPU    OFF CACHE BOOL "" FORCE)
    set(USE_CUDA   OFF CACHE BOOL "" FORCE)
    add_subdirectory(vendor/lightgbm EXCLUDE_FROM_ALL)
    # LightGBM's actual build target is '_lightgbm' (STATIC or SHARED depending
    # on BUILD_SHARED_LIBS).  Older releases used 'lightgbm' / 'lightgbm_static'.
    # Expose whichever exists under the canonical namespaced name.
    foreach(_lgbm_tgt IN ITEMS _lightgbm lightgbm_static lightgbm)
        if(TARGET ${_lgbm_tgt} AND NOT TARGET LightGBM::lightgbm)
            add_library(LightGBM::lightgbm ALIAS ${_lgbm_tgt})
            break()
        endif()
    endforeach()
    set(HAVE_LIGHTGBM ON)
    # LightGBM uses add_subdirectory() and does not set INTERFACE_INCLUDE_DIRECTORIES
    # on its targets, so consumers outside the subdirectory don't get the headers.
    foreach(_lgbm_inc_tgt IN ITEMS _lightgbm lightgbm_static lightgbm)
        if(TARGET ${_lgbm_inc_tgt})
            target_include_directories(${_lgbm_inc_tgt} INTERFACE
                $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/vendor/lightgbm/include>
            )
            break()
        endif()
    endforeach()
    message(STATUS "LightGBM: vendor submodule")
else()
    # Fallback: CMake config → manual find_library
    find_package(LightGBM CONFIG QUIET)
    if(LightGBM_FOUND)
        set(HAVE_LIGHTGBM ON)
        message(STATUS "LightGBM: CMake config (system)")
    else()
        find_library(LIGHTGBM_LIB NAMES lightgbm _lightgbm lib_lightgbm
                     PATHS /opt/homebrew/lib /usr/local/lib
                           /usr/lib /usr/lib/x86_64-linux-gnu)
        find_path(LIGHTGBM_INCLUDE NAMES LightGBM/c_api.h
                  PATHS /opt/homebrew/include /usr/local/include /usr/include)
        if(LIGHTGBM_LIB AND LIGHTGBM_INCLUDE)
            set(HAVE_LIGHTGBM ON)
            add_library(LightGBM::lightgbm UNKNOWN IMPORTED)
            set_target_properties(LightGBM::lightgbm PROPERTIES
                IMPORTED_LOCATION             "${LIGHTGBM_LIB}"
                INTERFACE_INCLUDE_DIRECTORIES "${LIGHTGBM_INCLUDE}")
            message(STATUS "LightGBM: found at ${LIGHTGBM_LIB}")
        else()
            set(HAVE_LIGHTGBM OFF)
            if(APPLE)
                message(STATUS "LightGBM not found – ML disabled. Install: brew install lightgbm")
            else()
                message(STATUS "LightGBM not found – ML disabled. Install: sudo apt install liblightgbm-dev")
            endif()
        endif()
    endif()
endif()

if(HAVE_LIGHTGBM)
    add_compile_definitions(HAVE_LIGHTGBM)
endif()

# ── ONNX Runtime (optional, system only) ─────────────────────────────────────
find_package(onnxruntime CONFIG QUIET)
if(onnxruntime_FOUND)
    set(HAVE_ONNXRUNTIME ON)
    add_compile_definitions(HAVE_ONNXRUNTIME)
    message(STATUS "ONNX Runtime: found (sentiment ONNX inference enabled)")
else()
    set(HAVE_ONNXRUNTIME OFF)
    message(STATUS "ONNX Runtime not found – rule-based sentiment only")
endif()

# ── Eigen3 ───────────────────────────────────────────────────────────────────
# Header-only linear algebra.
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/eigen/CMakeLists.txt")
    add_subdirectory(vendor/eigen EXCLUDE_FROM_ALL)
    message(STATUS "Eigen3: vendor submodule")
else()
    find_package(Eigen3 CONFIG REQUIRED)
    message(STATUS "Eigen3: system package")
endif()

# ── SQLite3 ──────────────────────────────────────────────────────────────────
# SQLite's git repo is a fossil mirror and does NOT contain sqlite3.c (it is a
# generated amalgamation).  Preferred approach for cross-compilation: place the
# two amalgamation files directly in vendor/sqlite/ and commit them to the repo:
#
#   wget https://www.sqlite.org/2024/sqlite-amalgamation-3460100.zip
#   unzip -j sqlite-amalgamation-3460100.zip -d vendor/sqlite/
#   git add vendor/sqlite/sqlite3.c vendor/sqlite/sqlite3.h
#
# Fallback 1 – system find_package (host builds where libsqlite3-dev is present).
# Fallback 2 – FetchContent auto-download of the amalgamation.
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/sqlite/sqlite3.c")
    add_library(sqlite3_vendor STATIC
        "${CMAKE_CURRENT_SOURCE_DIR}/vendor/sqlite/sqlite3.c")
    target_include_directories(sqlite3_vendor PUBLIC
        "${CMAKE_CURRENT_SOURCE_DIR}/vendor/sqlite")
    target_compile_definitions(sqlite3_vendor PUBLIC
        SQLITE_THREADSAFE=1
        SQLITE_ENABLE_JSON1
        SQLITE_ENABLE_FTS5
        SQLITE_ENABLE_RTREE)
    if(NOT TARGET SQLite::SQLite3)
        add_library(SQLite::SQLite3 ALIAS sqlite3_vendor)
    endif()
    message(STATUS "SQLite3: vendor amalgamation (vendor/sqlite/sqlite3.c)")
else()
    find_package(SQLite3 QUIET)
    if(SQLite3_FOUND)
        message(STATUS "SQLite3: system package (${SQLite3_VERSION})")
    else()
        message(STATUS "SQLite3: not in vendor and not installed – downloading amalgamation via FetchContent")
        include(FetchContent)
        FetchContent_Declare(
            sqlite3_src
            URL "https://www.sqlite.org/2024/sqlite-amalgamation-3460100.zip"
        )
        FetchContent_MakeAvailable(sqlite3_src)
        add_library(sqlite3_vendor STATIC "${sqlite3_src_SOURCE_DIR}/sqlite3.c")
        target_include_directories(sqlite3_vendor PUBLIC "${sqlite3_src_SOURCE_DIR}")
        target_compile_definitions(sqlite3_vendor PUBLIC
            SQLITE_THREADSAFE=1
            SQLITE_ENABLE_JSON1
            SQLITE_ENABLE_FTS5
            SQLITE_ENABLE_RTREE)
        if(NOT TARGET SQLite::SQLite3)
            add_library(SQLite::SQLite3 ALIAS sqlite3_vendor)
        endif()
        message(STATUS "SQLite3: FetchContent amalgamation 3.46.1")
    endif()
endif()

# ── Abseil-cpp (required by re2) ─────────────────────────────────────────────
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/abseil-cpp/CMakeLists.txt")
    set(ABSL_PROPAGATE_CXX_STD ON  CACHE BOOL "" FORCE)
    set(ABSL_ENABLE_INSTALL    OFF CACHE BOOL "" FORCE)
    # Suppress install() calls so they don't pollute the install manifest or
    # trigger "target not in export set" validation errors downstream.
    set(CMAKE_SKIP_INSTALL_RULES ON)
    add_subdirectory(vendor/abseil-cpp EXCLUDE_FROM_ALL)
    set(CMAKE_SKIP_INSTALL_RULES OFF)
    message(STATUS "Abseil: vendor submodule")
endif()

# ── re2 ──────────────────────────────────────────────────────────────────────
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/re2/CMakeLists.txt")
    set(RE2_BUILD_TESTING OFF CACHE BOOL "" FORCE)
    # re2's install(EXPORT "re2Targets") references absl:: targets which are
    # not in any export set (absl has ABSL_ENABLE_INSTALL=OFF).  Suppress all
    # install rules inside re2 to avoid the validation error.
    set(CMAKE_SKIP_INSTALL_RULES ON)
    add_subdirectory(vendor/re2 EXCLUDE_FROM_ALL)
    set(CMAKE_SKIP_INSTALL_RULES OFF)
    if(TARGET re2 AND NOT TARGET re2::re2)
        add_library(re2::re2 ALIAS re2)
    endif()
    message(STATUS "re2: vendor submodule")
else()
    find_package(re2 CONFIG REQUIRED)
    message(STATUS "re2: system package")
endif()

# ── CURL ─────────────────────────────────────────────────────────────────────
# vendor/curl ≥ 8.x requires OpenSSL 3.0.0+. Fall back to the system libcurl
# when the system only provides OpenSSL 1.x (e.g. Debian Buster).
find_package(OpenSSL QUIET)  # already done below, but we need the version here
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/curl/CMakeLists.txt"
   AND OPENSSL_FOUND
   AND NOT OPENSSL_VERSION VERSION_LESS "3.0.0")
    set(BUILD_CURL_EXE       OFF CACHE BOOL "" FORCE)
    set(BUILD_TESTING        OFF CACHE BOOL "" FORCE)
    # SSL/TLS: use the system OpenSSL (the one system-only dep we keep).
    set(CURL_USE_OPENSSL     ON  CACHE BOOL "" FORCE)
    set(CURL_ENABLE_SSL      ON  CACHE BOOL "" FORCE)
    # Disable all optional system deps so CURL builds standalone from vendor.
    # (These features are irrelevant for a trading-data HTTP client.)
    set(CURL_USE_LIBPSL      OFF CACHE BOOL "" FORCE)  # Public Suffix List
    set(CURL_USE_LIBSSH2     OFF CACHE BOOL "" FORCE)  # SCP/SFTP
    set(USE_LIBIDN2          OFF CACHE BOOL "" FORCE)  # internationalised domain names
    set(CURL_USE_NGHTTP2     OFF CACHE BOOL "" FORCE)  # HTTP/2 (needs nghttp2)
    set(CURL_USE_NGTCP2      OFF CACHE BOOL "" FORCE)  # HTTP/3 (needs ngtcp2)
    set(CURL_USE_QUICHE      OFF CACHE BOOL "" FORCE)  # HTTP/3 alt backend
    set(CURL_USE_LIBRTMP     OFF CACHE BOOL "" FORCE)  # RTMP streaming
    set(CURL_USE_GSSAPI      OFF CACHE BOOL "" FORCE)  # Kerberos/GSSAPI
    set(CURL_ZLIB            OFF CACHE BOOL "" FORCE)  # content compression
    # Force static build without polluting the global BUILD_SHARED_LIBS.
    set(_trade_bsl_save "${BUILD_SHARED_LIBS}")
    set(BUILD_SHARED_LIBS OFF)
    add_subdirectory(vendor/curl EXCLUDE_FROM_ALL)
    if(DEFINED _trade_bsl_save)
        set(BUILD_SHARED_LIBS "${_trade_bsl_save}")
    else()
        unset(BUILD_SHARED_LIBS)
    endif()
    # CURL ≥ 7.74 creates CURL::libcurl automatically; guard for older releases.
    if(TARGET libcurl_static AND NOT TARGET CURL::libcurl)
        add_library(CURL::libcurl ALIAS libcurl_static)
    endif()
    message(STATUS "CURL: vendor submodule")
else()
    find_package(CURL REQUIRED)
    if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/curl/CMakeLists.txt" AND OPENSSL_FOUND)
        message(STATUS "CURL: system package (vendor curl requires OpenSSL 3+, found ${OPENSSL_VERSION})")
    else()
        message(STATUS "CURL: system package")
    endif()
endif()

# ── Arrow & Parquet ──────────────────────────────────────────────────────────
# Building from source: Arrow downloads its own internal deps (Thrift,
# Flatbuffers, compression libs) on first configure via BUNDLED mode.
# These downloads are cached – subsequent configures are instant.
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/arrow/cpp/CMakeLists.txt")
    message(STATUS "Arrow/Parquet: vendor submodule (first cmake run downloads Arrow's bundled deps)")
    set(ARROW_BUILD_SHARED       ON  CACHE BOOL "" FORCE)
    set(ARROW_BUILD_STATIC       OFF CACHE BOOL "" FORCE)
    set(ARROW_PARQUET            ON  CACHE BOOL "" FORCE)
    set(ARROW_IPC                ON  CACHE BOOL "" FORCE)
    set(ARROW_FILESYSTEM         ON  CACHE BOOL "" FORCE)
    set(ARROW_COMPUTE            OFF CACHE BOOL "" FORCE)
    set(ARROW_CSV                OFF CACHE BOOL "" FORCE)
    set(ARROW_DATASET            OFF CACHE BOOL "" FORCE)
    set(ARROW_BUILD_TESTS        OFF CACHE BOOL "" FORCE)
    set(ARROW_BUILD_BENCHMARKS   OFF CACHE BOOL "" FORCE)
    set(ARROW_BUILD_UTILITIES    OFF CACHE BOOL "" FORCE)
    set(ARROW_WITH_UTF8PROC      OFF CACHE BOOL "" FORCE)
    # BUNDLED: Arrow downloads and builds its own internal dependencies.
    # Arrow isolates these internally; they do not conflict with our absl/re2.
    set(ARROW_DEPENDENCY_SOURCE  "BUNDLED" CACHE STRING "" FORCE)
    # Pin Arrow binary dir at top-level build tree to avoid duplicated
    # external-project paths after engine/ migration.
    set(_trade_arrow_binary_dir "${CMAKE_BINARY_DIR}/vendor/arrow/cpp")
    add_subdirectory(vendor/arrow/cpp "${_trade_arrow_binary_dir}" EXCLUDE_FROM_ALL)
    # Arrow creates 'arrow_shared' / 'parquet_shared' as the real build targets.
    # The Arrow:: namespace aliases only exist in the installed CMake config
    # (ArrowConfig.cmake), NOT when using add_subdirectory – create them here.
    if(TARGET arrow_shared AND NOT TARGET Arrow::arrow_shared)
        add_library(Arrow::arrow_shared ALIAS arrow_shared)
    endif()
    if(TARGET parquet_shared AND NOT TARGET Parquet::parquet_shared)
        add_library(Parquet::parquet_shared ALIAS parquet_shared)
    endif()
    # Arrow uses include_directories() (directory-scoped) instead of
    # target_include_directories(INTERFACE), so its headers are NOT propagated
    # to consumers outside the Arrow subdirectory.  Fix this explicitly.
    if(TARGET arrow_shared)
        target_include_directories(arrow_shared INTERFACE
            $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/vendor/arrow/cpp/src>
            $<BUILD_INTERFACE:${_trade_arrow_binary_dir}/src>
        )
    endif()
    if(TARGET parquet_shared)
        target_include_directories(parquet_shared INTERFACE
            $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/vendor/arrow/cpp/src>
            $<BUILD_INTERFACE:${_trade_arrow_binary_dir}/src>
        )
    endif()
else()
    find_package(Arrow   REQUIRED)
    find_package(Parquet REQUIRED)
    message(STATUS "Arrow/Parquet: system package")
endif()

# ── OpenSSL (system only – security-sensitive) ────────────────────────────────
find_package(OpenSSL REQUIRED)

# ── GoogleTest ───────────────────────────────────────────────────────────────
if(BUILD_TESTING)
    if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/vendor/googletest/CMakeLists.txt")
        set(BUILD_GMOCK            ON  CACHE BOOL "" FORCE)
        set(INSTALL_GTEST          OFF CACHE BOOL "" FORCE)
        set(gtest_force_shared_crt OFF CACHE BOOL "" FORCE)
        add_subdirectory(vendor/googletest EXCLUDE_FROM_ALL)
        # Ensure the GTest:: namespace aliases exist (googletest ≥ 1.11 adds them,
        # but older releases may not).
        if(TARGET gtest AND NOT TARGET GTest::gtest)
            add_library(GTest::gtest      ALIAS gtest)
            add_library(GTest::gtest_main ALIAS gtest_main)
        endif()
        message(STATUS "GoogleTest: vendor submodule")
    endif()
    # If not using submodule, tests.cmake will call find_package(GTest) itself.
endif()
