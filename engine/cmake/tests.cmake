function(trade_configure_tests)
    enable_testing()
    if(NOT TARGET GTest::gtest)
        find_package(GTest CONFIG REQUIRED)
    endif()
    include(GoogleTest)

    # Fix GTest include: convert SYSTEM include to normal include
    # to ensure Homebrew headers are found before /usr/local/include
    get_target_property(_gtest_inc GTest::gtest INTERFACE_INCLUDE_DIRECTORIES)
    if(_gtest_inc)
        set_target_properties(GTest::gtest PROPERTIES
            INTERFACE_INCLUDE_DIRECTORIES ""
            INTERFACE_SYSTEM_INCLUDE_DIRECTORIES "")
        target_include_directories(GTest::gtest INTERFACE ${_gtest_inc})
    endif()
    get_target_property(_gmain_inc GTest::gtest_main INTERFACE_INCLUDE_DIRECTORIES)
    if(_gmain_inc)
        set_target_properties(GTest::gtest_main PROPERTIES
            INTERFACE_INCLUDE_DIRECTORIES ""
            INTERFACE_SYSTEM_INCLUDE_DIRECTORIES "")
        target_include_directories(GTest::gtest_main INTERFACE ${_gmain_inc})
    endif()

    function(add_trade_test TEST_NAME TEST_SOURCE)
        add_executable(${TEST_NAME} ${TEST_SOURCE})
        target_link_libraries(${TEST_NAME} PRIVATE trade_core GTest::gtest_main)
        gtest_discover_tests(${TEST_NAME} DISCOVERY_TIMEOUT 30)
    endfunction()

    add_trade_test(test_types tests/unit/test_types.cpp)
    add_trade_test(test_bar tests/unit/test_bar.cpp)
    add_trade_test(test_parquet tests/unit/test_parquet.cpp)
    add_trade_test(test_metadata tests/unit/test_metadata.cpp)
    add_trade_test(test_normalizer tests/unit/test_normalizer.cpp)
    add_trade_test(test_validator tests/unit/test_validator.cpp)
    add_trade_test(test_features tests/unit/test_features.cpp)
    add_trade_test(test_stats tests/unit/test_stats.cpp)
    if(HAVE_LIGHTGBM)
        add_trade_test(test_ml tests/unit/test_ml.cpp)
    endif()
    add_trade_test(test_risk tests/unit/test_risk.cpp)
    add_trade_test(test_backtest tests/unit/test_backtest.cpp)
    add_trade_test(test_decision tests/unit/test_decision.cpp)
    add_trade_test(test_regime tests/unit/test_regime.cpp)
    add_trade_test(test_duck_store tests/unit/test_duck_store.cpp)
    add_trade_test(test_propagation tests/unit/test_propagation.cpp)
    add_trade_test(test_technical_signals tests/unit/test_technical_signals.cpp)
    add_trade_test(test_fundamental_features tests/unit/test_fundamental_features.cpp)
    add_trade_test(test_smart_money tests/unit/test_smart_money.cpp)

    add_trade_test(test_google_drive_sync tests/unit/test_google_drive_sync.cpp)

    add_trade_test(test_pipeline tests/integration/test_pipeline.cpp)
endfunction()
