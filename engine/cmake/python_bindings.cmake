function(trade_configure_python_bindings)
    find_package(Python COMPONENTS Interpreter Development.Module REQUIRED)
    include(FetchContent)
    FetchContent_Declare(
        nanobind
        GIT_REPOSITORY https://github.com/wjakob/nanobind.git
        GIT_TAG v2.4.0
    )
    FetchContent_MakeAvailable(nanobind)

    nanobind_add_module(trade_py
        python/bindings/module.cpp
        python/bindings/bind_model.cpp
        python/bindings/bind_features.cpp
        python/bindings/bind_ml.cpp
        python/bindings/bind_risk.cpp
        python/bindings/bind_regime.cpp
        python/bindings/bind_backtest.cpp
        python/bindings/bind_sentiment.cpp
        python/bindings/bind_decision.cpp
    )
    target_link_libraries(trade_py PRIVATE trade_core)
endfunction()
