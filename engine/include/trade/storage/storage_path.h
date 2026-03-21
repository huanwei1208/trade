#pragma once

#include "trade/common/types.h"
#include <string>
#include <filesystem>

namespace trade {

// Constructs standardized storage paths
// e.g., data/raw/cn_a/daily/2024/600000.SH.parquet
class StoragePath {
public:
    explicit StoragePath(const std::string& data_root);

    // Market data paths
    std::string raw_daily(const Symbol& symbol, int year) const;
    std::string silver_daily(const Symbol& symbol, int year) const;
    std::string raw_daily_bucket(int year, int bucket) const;
    std::string silver_daily_bucket(int year, int bucket) const;
    static int bucket_for_symbol(const Symbol& symbol, int bucket_count);

    // Model paths
    std::string model_file(const std::string& name) const;

    // Future data paths
    std::string raw_minute(const Symbol& symbol, int year, int month) const;
    std::string raw_tick(const Symbol& symbol, Date date) const;

    // Models directory
    std::string models_dir() const;

    // New monthly kline paths (replaces bucketed raw/silver layout)
    // Returns: data/market/kline/{symbol}.parquet (prefers flat layout, falls back to legacy root/kline)
    std::string kline_flat(const Symbol& symbol) const;
    // Returns: data/market/kline/YYYY-MM/{symbol}.parquet in legacy monthly layout
    std::string kline_monthly(const Symbol& symbol, int year, int month) const;
    // Returns: data/market/kline/YYYY-MM/ directory
    std::string kline_dir(int year, int month) const;

    // Metadata
    std::string metadata_db() const;

    // Ensure directory exists
    static void ensure_dir(const std::string& path);

private:
    std::filesystem::path kline_root() const;
    static std::string safe_symbol(const Symbol& symbol);
    std::filesystem::path root_;
};

} // namespace trade
