#include "trade/storage/storage_path.h"
#include <algorithm>
#include "trade/common/time_utils.h"
#include <chrono>
#include <fmt/format.h>
#include <functional>

namespace trade {

StoragePath::StoragePath(const std::string& data_root) : root_(data_root) {}

std::filesystem::path StoragePath::kline_root() const {
    const auto market = root_ / "market" / "kline";
    if (std::filesystem::exists(market)) return market;
    const auto legacy = root_ / "kline";
    if (std::filesystem::exists(legacy)) return legacy;
    return market;
}

std::string StoragePath::safe_symbol(const Symbol& symbol) {
    auto safe = symbol;
    std::replace(safe.begin(), safe.end(), "."[0], "_"[0]);
    return safe;
}

std::string StoragePath::raw_daily(const Symbol& symbol, int year) const {
    return (root_ / "raw" / "cn_a" / "daily" / std::to_string(year) /
            (symbol + ".parquet")).string();
}

std::string StoragePath::silver_daily(const Symbol& symbol, int year) const {
    return (root_ / "silver" / "cn_a" / "daily" / std::to_string(year) /
            (symbol + ".parquet")).string();
}

std::string StoragePath::raw_daily_bucket(int year, int bucket) const {
    return (root_ / "raw" / "cn_a" / "daily" / std::to_string(year) /
            fmt::format("bucket={:02d}", bucket) / "part-000.parquet").string();
}

std::string StoragePath::silver_daily_bucket(int year, int bucket) const {
    return (root_ / "silver" / "cn_a" / "daily" / std::to_string(year) /
            fmt::format("bucket={:02d}", bucket) / "part-000.parquet").string();
}

int StoragePath::bucket_for_symbol(const Symbol& symbol, int bucket_count) {
    if (bucket_count <= 0) return 0;
    return static_cast<int>(std::hash<std::string>{}(symbol) %
                            static_cast<size_t>(bucket_count));
}

std::string StoragePath::model_file(const std::string& name) const {
    return (root_ / "models" / (name + ".model")).string();
}

std::string StoragePath::raw_minute(const Symbol& symbol, int year, int month) const {
    return (root_ / "raw" / "cn_a" / "minute" / std::to_string(year) /
            fmt::format("{:02d}", month) / (symbol + ".parquet")).string();
}

std::string StoragePath::raw_tick(const Symbol& symbol, Date date) const {
    auto ymd = std::chrono::year_month_day{date};
    int year = static_cast<int>(ymd.year());
    unsigned month = static_cast<unsigned>(ymd.month());
    unsigned day = static_cast<unsigned>(ymd.day());
    return (root_ / "raw" / "cn_a" / "tick" / std::to_string(year) /
            fmt::format("{:02d}", month) / fmt::format("{:02d}", day) /
            (symbol + ".parquet")).string();
}

std::string StoragePath::models_dir() const {
    return (root_ / "models").string();
}

std::string StoragePath::metadata_db() const {
    return (root_ / "metadata.db").string();
}

void StoragePath::ensure_dir(const std::string& path) {
    auto parent = std::filesystem::path(path).parent_path();
    if (!parent.empty()) {
        std::filesystem::create_directories(parent);
    }
}

std::string StoragePath::kline_flat(const Symbol& symbol) const {
    return (kline_root() / (safe_symbol(symbol) + ".parquet")).string();
}

std::string StoragePath::kline_monthly(const Symbol& symbol, int year, int month) const {
    return (kline_root() /
            fmt::format("{:04d}-{:02d}", year, month) /
            (safe_symbol(symbol) + ".parquet")).string();
}

std::string StoragePath::kline_dir(int year, int month) const {
    return (kline_root() /
            fmt::format("{:04d}-{:02d}", year, month)).string();
}

} // namespace trade
