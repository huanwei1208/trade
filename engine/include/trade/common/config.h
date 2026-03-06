#pragma once

#include <string>
#include <vector>
#include <yaml-cpp/yaml.h>

namespace trade {

struct DataConfig {
    std::string data_root = "data";
    std::string models_dir = "models";  // relative to data_root
};

// min_start_date is the only actively-used ingestion parameter in C++.
// All other ingestion settings (rate limits, dedup, streaming) are Python-side only.
struct IngestionConfig {
    std::string min_start_date = "2020-01-01";
};

struct StorageConfig {
    bool enabled = false;
    std::string backend = "local";       // local | google_drive
    std::string write_mode = "local_only"; // local_only | hybrid | cloud_only
    int hot_days = 30;
    bool keep_local_cold_copy = false;
    bool mirror_hot_to_cloud = false;
    // Google Drive credentials
    std::string google_drive_key_file = "";
    std::string google_drive_folder_id = "";
    int google_drive_timeout_ms = 30000;
    int google_drive_retry_count = 2;
};

struct SecurityConfig {
    std::string default_role = "user";
    std::string admin_token = "";
};

// Kept as standalone struct — used by BacktestEngine / BrokerSim as a parameter type.
// Runtime values come from the settings table in data/.metadata/trade.db (via Python).
struct TradingCostConfig {
    double stamp_tax_rate = 0.0005;       // 印花税 0.05% (卖出)
    double commission_rate = 0.00025;     // 佣金 0.025% (双向)
    double commission_min_yuan = 5.0;     // 最低佣金 5元
    double transfer_fee_rate = 0.00001;   // 过户费 0.001% (沪市)
};

// Kept as standalone struct — used by BacktestEngine.
// Runtime values come from the settings table (via Python).
struct BacktestConfig {
    double initial_capital = 1000000.0;
    int max_positions = 25;
    int min_positions = 15;
    double min_adv_participation = 0.08;
    double max_adv_participation = 0.12;
    double rebalance_threshold = 0.01;
    double alpha_cost_multiple = 1.5;
};

struct Config {
    DataConfig data;
    IngestionConfig ingestion;  // only min_start_date
    StorageConfig storage;
    SecurityConfig security;
    // BacktestConfig and TradingCostConfig are standalone structs (not in Config).
    // Their runtime values come from the settings table in data/.metadata/trade.db.
    BacktestConfig backtest;    // kept for CLI commands_analysis backtest command

    static Config load(const std::string& path);
    static Config defaults();
};

} // namespace trade
