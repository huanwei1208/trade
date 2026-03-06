# Source groups for modular core build.

set(TRADE_BASE_SOURCES
    src/common/config.cpp
    src/common/time_utils.cpp
    src/model/bar.cpp
    src/model/instrument.cpp
)

set(TRADE_DATA_SOURCES
    src/storage/parquet_writer.cpp
    src/storage/parquet_reader.cpp
    src/storage/metadata_store.cpp
    src/storage/storage_path.cpp
    src/storage/duck_store.cpp
    src/storage/cloud_sync.cpp
    src/storage/google_drive_sync.cpp
    # provider/collector sources removed: data ingestion migrated to Python/akshare
    # src/provider/provider_factory.cpp
    # src/provider/http_client.cpp
    # src/provider/eastmoney_provider.cpp
    # src/provider/eastmoney_fundamental.cpp
    # src/collector/collector.cpp
    src/normalizer/bar_normalizer.cpp
    src/validator/data_validator.cpp
)

set(TRADE_FEATURE_SOURCES
    src/features/feature_engine.cpp
    src/features/preprocessor.cpp
    src/features/momentum.cpp
    src/features/volatility.cpp
    src/features/liquidity.cpp
    src/features/fund_flow.cpp
    src/features/price_limit.cpp
    src/features/industry.cpp
    src/features/interaction.cpp
    src/features/calendar.cpp
    src/features/fundamental.cpp
    src/features/feature_monitor.cpp
    src/features/technical_signals.cpp
    src/features/fundamental_features.cpp
    src/features/smart_money_signal.cpp
)

set(TRADE_STATS_SOURCES
    src/stats/descriptive.cpp
    src/stats/correlation.cpp
    src/stats/attribution.cpp
)

set(TRADE_ML_SOURCES
    src/ml/lgbm_model.cpp
    src/ml/model_trainer.cpp
    src/ml/model_evaluator.cpp
)

set(TRADE_RISK_SOURCES
    src/risk/covariance.cpp
    src/risk/var.cpp
    src/risk/kelly.cpp
    src/risk/position_sizer.cpp
    src/risk/drawdown.cpp
    src/risk/stress_test.cpp
    src/risk/risk_monitor.cpp
    src/risk/risk_attribution.cpp
)

set(TRADE_REGIME_SOURCES
    src/regime/regime_detector.cpp
)

set(TRADE_BACKTEST_SOURCES
    src/backtest/backtest_engine.cpp
    src/backtest/broker_sim.cpp
    src/backtest/portfolio_state.cpp
    src/backtest/strategy.cpp
    src/backtest/slippage.cpp
    src/backtest/performance.cpp
    src/backtest/validation.cpp
    src/backtest/reporting.cpp
)

set(TRADE_SENTIMENT_SOURCES
)

set(TRADE_DECISION_SOURCES
    src/decision/signal_combiner.cpp
    src/decision/universe_filter.cpp
    src/decision/portfolio_opt.cpp
    src/decision/order_manager.cpp
    src/decision/pre_trade_check.cpp
    src/decision/decision_report.cpp
)

set(TRADE_SIGNAL_SOURCES
    src/signal/propagation.cpp
)

set(TRADE_APP_SOURCES
    # download_pipeline.cpp removed: data ingestion migrated to Python/akshare
    # src/app/pipelines/download_pipeline.cpp
    src/app/pipelines/train_pipeline.cpp
)
