#include "trade/storage/parquet_reader.h"
#include "trade/common/time_utils.h"
#include "trade/storage/google_drive_sync.h"
#include <arrow/io/file.h>
#include <parquet/arrow/reader.h>
#include <spdlog/spdlog.h>
#include <filesystem>
#include <fstream>

namespace trade {

namespace {

struct RuntimeStorage {
    bool configured = false;
    DataConfig data;
    StorageConfig storage;
};

RuntimeStorage& runtime_storage() {
    static RuntimeStorage cfg;
    return cfg;
}

bool path_prefix_match(const std::filesystem::path& path,
                       const std::filesystem::path& prefix) {
    auto pit = path.begin();
    auto qit = prefix.begin();
    for (; qit != prefix.end(); ++pit, ++qit) {
        if (pit == path.end() || *pit != *qit) {
            return false;
        }
    }
    return true;
}

std::string to_rel_data_path(const std::string& path, const std::string& data_root) {
    std::filesystem::path p = std::filesystem::path(path).lexically_normal();
    std::filesystem::path root = std::filesystem::path(data_root).lexically_normal();

    if (path_prefix_match(p, root)) {
        auto rel = p.lexically_relative(root);
        return rel.generic_string();
    }

    std::string s = p.generic_string();
    std::string root_s = root.generic_string();
    if (!root_s.empty() && s.rfind(root_s + "/", 0) == 0) {
        return s.substr(root_s.size() + 1);
    }
    return s;
}

bool cloud_enabled() {
    const auto& rt = runtime_storage();
    if (!rt.configured || !rt.storage.enabled) return false;
    return rt.storage.backend == "google_drive";
}

bool download_to_local_if_missing(const std::string& path) {
    if (std::filesystem::exists(path)) return true;
    if (!cloud_enabled()) return false;

    const auto& rt = runtime_storage();
    GoogleDriveSync client({
        .service_account_json_path = rt.storage.google_drive_key_file,
        .root_folder_id = rt.storage.google_drive_folder_id,
        .timeout_ms = rt.storage.google_drive_timeout_ms,
        .retry_count = rt.storage.google_drive_retry_count,
    });

    std::string rel = to_rel_data_path(path, rt.data.data_root);
    std::vector<uint8_t> bytes;
    if (!client.download_bytes(rel, &bytes) || bytes.empty()) {
        return false;
    }

    auto parent = std::filesystem::path(path).parent_path();
    if (!parent.empty()) {
        std::filesystem::create_directories(parent);
    }
    std::ofstream ofs(path, std::ios::binary | std::ios::trunc);
    if (!ofs.is_open()) return false;
    ofs.write(reinterpret_cast<const char*>(bytes.data()),
              static_cast<std::streamsize>(bytes.size()));
    if (!ofs.good()) return false;

    spdlog::info("Hydrated parquet from cloud: {}", path);
    return true;
}

std::shared_ptr<arrow::io::RandomAccessFile> open_random_access(
    const std::string& path) {
    auto infile = arrow::io::ReadableFile::Open(path);
    if (infile.ok()) return *infile;

    if (download_to_local_if_missing(path)) {
        infile = arrow::io::ReadableFile::Open(path);
        if (infile.ok()) return *infile;
    }
    return nullptr;
}

std::unique_ptr<parquet::arrow::FileReader> open_parquet_reader(
    const std::string& path) {
    auto input = open_random_access(path);
    if (!input) {
        spdlog::error("Failed to open {} locally or from cloud", path);
        return nullptr;
    }

    auto reader_result = parquet::arrow::OpenFile(input, arrow::default_memory_pool());
    if (!reader_result.ok()) {
        spdlog::error("Failed to open parquet reader for {}: {}",
                      path, reader_result.status().ToString());
        return nullptr;
    }
    return std::move(*reader_result);
}

Bar row_to_bar(const std::shared_ptr<arrow::Table>& table, int64_t row) {
    Bar bar;
    auto get_string = [&](const std::string& col) -> std::string {
        auto column = table->GetColumnByName(col);
        if (!column) return "";
        auto arr = std::static_pointer_cast<arrow::StringArray>(column->chunk(0));
        return arr->GetString(row);
    };
    auto get_double = [&](const std::string& col) -> double {
        auto column = table->GetColumnByName(col);
        if (!column) return 0.0;
        auto arr = std::static_pointer_cast<arrow::DoubleArray>(column->chunk(0));
        if (arr->IsNull(row)) return 0.0;
        return arr->Value(row);
    };
    auto get_optional_double = [&](const std::string& col) -> std::optional<double> {
        auto column = table->GetColumnByName(col);
        if (!column) return std::nullopt;
        auto arr = std::static_pointer_cast<arrow::DoubleArray>(column->chunk(0));
        if (arr->IsNull(row)) return std::nullopt;
        return arr->Value(row);
    };
    auto get_int64 = [&](const std::string& col) -> int64_t {
        auto column = table->GetColumnByName(col);
        if (!column) return 0;
        auto arr = std::static_pointer_cast<arrow::Int64Array>(column->chunk(0));
        if (arr->IsNull(row)) return 0;
        return arr->Value(row);
    };
    auto get_bool = [&](const std::string& col) -> bool {
        auto column = table->GetColumnByName(col);
        if (!column) return false;
        auto arr = std::static_pointer_cast<arrow::BooleanArray>(column->chunk(0));
        if (arr->IsNull(row)) return false;
        return arr->Value(row);
    };
    auto get_uint8 = [&](const std::string& col) -> uint8_t {
        auto column = table->GetColumnByName(col);
        if (!column) return 0;
        auto arr = std::static_pointer_cast<arrow::UInt8Array>(column->chunk(0));
        if (arr->IsNull(row)) return 0;
        return arr->Value(row);
    };

    bar.symbol = get_string("symbol");
    bar.date = parse_date(get_string("date"));
    bar.open = get_double("open");
    bar.high = get_double("high");
    bar.low = get_double("low");
    bar.close = get_double("close");
    bar.volume = get_int64("volume");
    bar.amount = get_double("amount");
    bar.turnover_rate = get_double("turnover_rate");
    bar.prev_close = get_double("prev_close");
    bar.vwap = get_double("vwap");

    // Extended fields (schema evolution: missing columns → defaults)
    bar.limit_up = get_double("limit_up");
    bar.limit_down = get_double("limit_down");
    bar.hit_limit_up = get_bool("hit_limit_up");
    bar.hit_limit_down = get_bool("hit_limit_down");
    // Support both old "status" and new "bar_status" column names
    if (table->GetColumnByName("bar_status")) {
        bar.bar_status = static_cast<TradingStatus>(get_uint8("bar_status"));
    } else {
        bar.bar_status = static_cast<TradingStatus>(get_uint8("status"));
    }
    bar.board = static_cast<Board>(get_uint8("board"));

    bar.north_net_buy = get_optional_double("north_net_buy");
    bar.margin_balance = get_optional_double("margin_balance");
    bar.short_sell_volume = get_optional_double("short_sell_volume");

    return bar;
}

} // namespace

void ParquetReader::configure_runtime(const DataConfig& data_cfg,
                                      const StorageConfig& storage_cfg) {
    auto& rt = runtime_storage();
    rt.configured = true;
    rt.data = data_cfg;
    rt.storage = storage_cfg;
}

std::vector<Bar> ParquetReader::read_bars(const std::string& path) {
    auto table = read_table(path);
    if (!table) return {};

    std::vector<Bar> bars;
    bars.reserve(table->num_rows());
    for (int64_t i = 0; i < table->num_rows(); ++i) {
        bars.push_back(row_to_bar(table, i));
    }
    return bars;
}

std::vector<Bar> ParquetReader::read_bars(const std::string& path,
                                           std::optional<Date> start,
                                           std::optional<Date> end) {
    auto all = read_bars(path);
    if (!start && !end) return all;

    std::vector<Bar> filtered;
    for (auto& bar : all) {
        if (start && bar.date < *start) continue;
        if (end && bar.date > *end) continue;
        filtered.push_back(std::move(bar));
    }
    return filtered;
}

std::shared_ptr<arrow::Table> ParquetReader::read_table(const std::string& path) {
    auto reader = open_parquet_reader(path);
    if (!reader) return nullptr;

    std::shared_ptr<arrow::Table> table;
    auto status = reader->ReadTable(&table);
    if (!status.ok()) {
        spdlog::error("Failed to read table from {}: {}", path, status.ToString());
        return nullptr;
    }

    return table;
}

std::shared_ptr<arrow::Table> ParquetReader::read_columns(
    const std::string& path,
    const std::vector<std::string>& columns) {
    auto reader = open_parquet_reader(path);
    if (!reader) return nullptr;

    // Get column indices
    auto schema = reader->parquet_reader()->metadata()->schema();
    std::vector<int> indices;
    for (const auto& col : columns) {
        int idx = schema->ColumnIndex(col);
        if (idx >= 0) indices.push_back(idx);
    }

    std::shared_ptr<arrow::Table> table;
    auto status = reader->ReadTable(indices, &table);
    if (!status.ok()) return nullptr;
    return table;
}

int64_t ParquetReader::row_count(const std::string& path) {
    auto reader = open_parquet_reader(path);
    if (!reader) return -1;

    return reader->parquet_reader()->metadata()->num_rows();
}

} // namespace trade
