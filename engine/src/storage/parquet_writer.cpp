#include "trade/storage/parquet_writer.h"

#include "trade/common/time_utils.h"
#include "trade/storage/google_drive_sync.h"
#include "trade/storage/parquet_reader.h"
#include "trade/normalizer/bar_normalizer.h"

#include <arrow/builder.h>
#include <arrow/io/memory.h>
#include <arrow/io/file.h>
#include <arrow/table.h>
#include <filesystem>
#include <fstream>
#include <parquet/arrow/writer.h>
#include <spdlog/spdlog.h>
#include <unordered_map>

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

struct WriteDecision {
    bool write_local = true;
    bool write_cloud = false;
};

int days_old(Date d) {
    auto now = std::chrono::floor<std::chrono::days>(std::chrono::system_clock::now());
    auto diff = now - d;
    return static_cast<int>(std::chrono::duration_cast<std::chrono::days>(diff).count());
}

WriteDecision decide_write(const std::optional<Date>& partition_max_date) {
    const auto& rt = runtime_storage();
    if (!rt.configured || !rt.storage.enabled) {
        return {};
    }

    if (rt.storage.backend != "google_drive") {
        return {};
    }

    if (rt.storage.write_mode == "cloud_only") {
        return {.write_local = false, .write_cloud = true};
    }
    if (rt.storage.write_mode == "local_only") {
        return {.write_local = true, .write_cloud = false};
    }

    // Hybrid mode
    bool is_cold = false;
    if (partition_max_date.has_value()) {
        is_cold = days_old(*partition_max_date) > rt.storage.hot_days;
    }
    if (is_cold) {
        return {.write_local = rt.storage.keep_local_cold_copy, .write_cloud = true};
    }
    return {.write_local = true, .write_cloud = rt.storage.mirror_hot_to_cloud};
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

std::vector<uint8_t> table_to_parquet_bytes(const std::shared_ptr<arrow::Table>& table) {
    auto sink_res = arrow::io::BufferOutputStream::Create();
    if (!sink_res.ok()) {
        spdlog::error("Failed to create in-memory parquet sink: {}", sink_res.status().ToString());
        return {};
    }
    auto sink = *sink_res;

    auto writer_props = parquet::WriterProperties::Builder()
                            .compression(parquet::Compression::SNAPPY)
                            ->build();
    auto status = parquet::arrow::WriteTable(*table,
                                             arrow::default_memory_pool(),
                                             sink,
                                             /*chunk_size=*/65536,
                                             writer_props);
    if (!status.ok()) {
        spdlog::error("Failed to encode parquet buffer: {}", status.ToString());
        return {};
    }

    auto finish_res = sink->Finish();
    if (!finish_res.ok()) {
        spdlog::error("Failed to finish parquet buffer: {}", finish_res.status().ToString());
        return {};
    }
    auto buf = *finish_res;
    return std::vector<uint8_t>(buf->data(), buf->data() + buf->size());
}

bool write_local_bytes(const std::string& path, const std::vector<uint8_t>& bytes) {
    auto parent = std::filesystem::path(path).parent_path();
    if (!parent.empty()) {
        std::filesystem::create_directories(parent);
    }

    std::ofstream ofs(path, std::ios::binary | std::ios::trunc);
    if (!ofs.is_open()) {
        spdlog::error("Failed to open {} for writing", path);
        return false;
    }
    ofs.write(reinterpret_cast<const char*>(bytes.data()),
              static_cast<std::streamsize>(bytes.size()));
    if (!ofs.good()) {
        spdlog::error("Failed to write {}", path);
        return false;
    }
    return true;
}

} // namespace

std::shared_ptr<arrow::Schema> ParquetStore::bar_schema() {
    return arrow::schema({
        arrow::field("symbol", arrow::utf8()),
        arrow::field("date", arrow::utf8()),
        arrow::field("open", arrow::float64()),
        arrow::field("high", arrow::float64()),
        arrow::field("low", arrow::float64()),
        arrow::field("close", arrow::float64()),
        arrow::field("volume", arrow::int64()),
        arrow::field("amount", arrow::float64()),
        arrow::field("turnover_rate", arrow::float64()),
        arrow::field("prev_close", arrow::float64()),
        arrow::field("vwap", arrow::float64()),
        arrow::field("limit_up", arrow::float64()),
        arrow::field("limit_down", arrow::float64()),
        arrow::field("hit_limit_up", arrow::boolean()),
        arrow::field("hit_limit_down", arrow::boolean()),
        arrow::field("bar_status", arrow::uint8()),
        arrow::field("board", arrow::uint8()),
        arrow::field("north_net_buy", arrow::float64()),
        arrow::field("margin_balance", arrow::float64()),
        arrow::field("short_sell_volume", arrow::float64()),
    });
}

std::shared_ptr<arrow::Table> ParquetStore::bars_to_table(const std::vector<Bar>& bars) {
    arrow::StringBuilder symbol_builder, date_builder;
    arrow::DoubleBuilder open_b, high_b, low_b, close_b, amount_b, turnover_b, prev_close_b, vwap_b;
    arrow::Int64Builder volume_b;
    arrow::DoubleBuilder limit_up_b, limit_down_b;
    arrow::BooleanBuilder hit_up_b, hit_down_b;
    arrow::UInt8Builder status_b, board_b;
    arrow::DoubleBuilder north_b, margin_b, short_b;

    for (const auto& bar : bars) {
        (void)symbol_builder.Append(bar.symbol);
        (void)date_builder.Append(format_date(bar.date));
        (void)open_b.Append(bar.open);
        (void)high_b.Append(bar.high);
        (void)low_b.Append(bar.low);
        (void)close_b.Append(bar.close);
        (void)volume_b.Append(bar.volume);
        (void)amount_b.Append(bar.amount);
        (void)turnover_b.Append(bar.turnover_rate);
        if (bar.prev_close > 0.0) {
            (void)prev_close_b.Append(bar.prev_close);
        } else {
            (void)prev_close_b.AppendNull();
        }
        if (bar.vwap > 0.0) {
            (void)vwap_b.Append(bar.vwap);
        } else {
            (void)vwap_b.AppendNull();
        }
        if (bar.limit_up > 0.0) {
            (void)limit_up_b.Append(bar.limit_up);
        } else {
            (void)limit_up_b.AppendNull();
        }
        if (bar.limit_down > 0.0) {
            (void)limit_down_b.Append(bar.limit_down);
        } else {
            (void)limit_down_b.AppendNull();
        }
        (void)hit_up_b.Append(bar.hit_limit_up);
        (void)hit_down_b.Append(bar.hit_limit_down);
        (void)status_b.Append(static_cast<uint8_t>(bar.bar_status));
        (void)board_b.Append(static_cast<uint8_t>(bar.board));
        if (bar.north_net_buy.has_value()) {
            (void)north_b.Append(*bar.north_net_buy);
        } else {
            (void)north_b.AppendNull();
        }
        if (bar.margin_balance.has_value()) {
            (void)margin_b.Append(*bar.margin_balance);
        } else {
            (void)margin_b.AppendNull();
        }
        if (bar.short_sell_volume.has_value()) {
            (void)short_b.Append(*bar.short_sell_volume);
        } else {
            (void)short_b.AppendNull();
        }
    }

    std::vector<std::shared_ptr<arrow::Array>> arrays(20);
    (void)symbol_builder.Finish(&arrays[0]);
    (void)date_builder.Finish(&arrays[1]);
    (void)open_b.Finish(&arrays[2]);
    (void)high_b.Finish(&arrays[3]);
    (void)low_b.Finish(&arrays[4]);
    (void)close_b.Finish(&arrays[5]);
    (void)volume_b.Finish(&arrays[6]);
    (void)amount_b.Finish(&arrays[7]);
    (void)turnover_b.Finish(&arrays[8]);
    (void)prev_close_b.Finish(&arrays[9]);
    (void)vwap_b.Finish(&arrays[10]);
    (void)limit_up_b.Finish(&arrays[11]);
    (void)limit_down_b.Finish(&arrays[12]);
    (void)hit_up_b.Finish(&arrays[13]);
    (void)hit_down_b.Finish(&arrays[14]);
    (void)status_b.Finish(&arrays[15]);
    (void)board_b.Finish(&arrays[16]);
    (void)north_b.Finish(&arrays[17]);
    (void)margin_b.Finish(&arrays[18]);
    (void)short_b.Finish(&arrays[19]);

    return arrow::Table::Make(bar_schema(), arrays);
}

void ParquetStore::write_bars(const std::string& path,
                              const std::vector<Bar>& bars,
                              MergeMode mode,
                              std::optional<Date> partition_max_date) {
    if (mode == MergeMode::kReplace) {
        write_table(path, bars_to_table(bars), partition_max_date);
        return;
    }

    std::unordered_map<Date, Bar> by_date;
    if (std::filesystem::exists(path)) {
        for (auto& b : ParquetReader::read_bars(path)) {
            by_date[b.date] = std::move(b);
        }
    }
    for (const auto& b : bars) {
        by_date[b.date] = b;
    }

    std::vector<Bar> merged;
    merged.reserve(by_date.size());
    for (auto& [_, b] : by_date) merged.push_back(std::move(b));
    merged = BarNormalizer::normalize(std::move(merged));

    write_table(path, bars_to_table(merged), partition_max_date);
}

void ParquetStore::write_table(const std::string& path,
                               const std::shared_ptr<arrow::Table>& table,
                               std::optional<Date> partition_max_date) {
    auto bytes = table_to_parquet_bytes(table);
    if (bytes.empty()) {
        spdlog::error("Failed to serialize parquet: {}", path);
        return;
    }

    WriteDecision decision = decide_write(partition_max_date);
    bool local_ok = true;
    bool cloud_ok = true;

    if (decision.write_local) {
        local_ok = write_local_bytes(path, bytes);
        if (local_ok) {
            spdlog::debug("Wrote {} rows to {}", table->num_rows(), path);
        }
    }

    if (decision.write_cloud) {
        const auto& rt = runtime_storage();
        GoogleDriveSync client({
            .service_account_json_path = rt.storage.google_drive_key_file,
            .root_folder_id = rt.storage.google_drive_folder_id,
            .timeout_ms = rt.storage.google_drive_timeout_ms,
            .retry_count = rt.storage.google_drive_retry_count,
        });
        const std::string rel_path = to_rel_data_path(path, rt.data.data_root);
        cloud_ok = client.upload_bytes(rel_path, bytes);

        if (cloud_ok && !decision.write_local && std::filesystem::exists(path)) {
            std::error_code ec;
            std::filesystem::remove(path, ec);
            if (ec) {
                spdlog::warn("Failed to remove local cold file {}: {}", path, ec.message());
            }
        }
    }

    if (!local_ok || !cloud_ok) {
        spdlog::error("Write failure for {} (local_ok={}, cloud_ok={})",
                      path, local_ok, cloud_ok);
        return;
    }
}

void ParquetStore::configure_runtime(const DataConfig& data_cfg,
                                     const StorageConfig& storage_cfg) {
    auto& rt = runtime_storage();
    rt.configured = true;
    rt.data = data_cfg;
    rt.storage = storage_cfg;
}

} // namespace trade
