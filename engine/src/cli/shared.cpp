#include "trade/cli/shared.h"

#include "trade/common/time_utils.h"
#include "trade/storage/duck_store.h"
#include "trade/storage/metadata_store.h"
#include "trade/storage/parquet_reader.h"
#include "trade/storage/storage_path.h"
#include <algorithm>
#include <cctype>
#include <chrono>
#include <filesystem>
#include <map>

namespace trade::cli {

std::pair<Date, Date> resolve_dates(const CliArgs& args,
                                    const std::string& default_start) {
    auto start = args.start_date.empty()
        ? parse_date(default_start)
        : parse_date(args.start_date);
    auto end = args.end_date.empty()
        ? std::chrono::floor<std::chrono::days>(std::chrono::system_clock::now())
        : parse_date(args.end_date);
    return {start, end};
}

std::vector<Bar> load_bars(const std::string& symbol,
                           const Config& config) {
    StoragePath paths(config.data.data_root);

    // Fast path: use DuckStore to scan all kline parquet files in one query.
    const std::string kline_dir =
        (std::filesystem::path(config.data.data_root) / "kline").string();
    if (std::filesystem::exists(kline_dir)) {
        const std::string glob =
            (std::filesystem::path(kline_dir) / "**" / "*.parquet").string();
        try {
            DuckStore db;
            auto bars = db.read_bars(glob, symbol);
            if (!bars.empty()) {
                return bars;
            }
        } catch (...) {
            // Fall through to year-loop below on any DuckStore failure.
        }
    }

    // Fallback: year/month file loop via ParquetReader.
    std::map<Date, Bar> by_date;
    auto now = std::chrono::floor<std::chrono::days>(std::chrono::system_clock::now());
    auto min_date = parse_date(config.ingestion.min_start_date);
    int start_year = date_year(min_date);
    int end_year = date_year(now);

    for (int year = start_year; year <= end_year; ++year) {
        for (int month = 1; month <= 12; ++month) {
            const std::string path = paths.kline_monthly(symbol, year, month);
            if (!std::filesystem::exists(path)) continue;
            try {
                auto bars = ParquetReader::read_bars(path);
                for (auto& bar : bars) {
                    if (bar.symbol == symbol || bar.symbol.empty()) {
                        by_date[bar.date] = std::move(bar);
                    }
                }
            } catch (...) {}
        }
    }

    std::vector<Bar> all_bars;
    all_bars.reserve(by_date.size());
    for (auto& [_, bar] : by_date) all_bars.push_back(std::move(bar));
    std::sort(all_bars.begin(), all_bars.end(),
              [](const Bar& a, const Bar& b) { return a.date < b.date; });
    return all_bars;
}

std::string sql_escape(const std::string& s) {
    std::string out;
    out.reserve(s.size());
    for (char c : s) {
        out.push_back(c);
        if (c == '\'') out.push_back('\'');
    }
    return out;
}

namespace {

std::string sanitize_view_name(std::string s) {
    for (char& c : s) {
        if (!(std::isalnum(static_cast<unsigned char>(c)) || c == '_')) {
            c = '_';
        }
    }
    if (s.empty()) s = "dataset";
    if (std::isdigit(static_cast<unsigned char>(s[0]))) {
        s = "d_" + s;
    }
    return s;
}

bool has_local_parquet(const std::filesystem::path& dir) {
    if (!std::filesystem::exists(dir)) return false;
    for (const auto& entry : std::filesystem::recursive_directory_iterator(dir)) {
        if (!entry.is_regular_file()) continue;
        if (entry.path().extension() == ".parquet") return true;
    }
    return false;
}

std::string sql_string(const std::string& s) {
    return "'" + sql_escape(s) + "'";
}

std::string sql_date_or_null(const std::optional<Date>& d) {
    if (!d) return "NULL";
    return sql_string(format_date(*d));
}

std::string build_values_view_sql(const std::string& view_name,
                                  const std::vector<std::string>& columns,
                                  const std::vector<std::vector<std::string>>& rows) {
    if (columns.empty()) return "";
    std::string out = "CREATE OR REPLACE VIEW " + view_name + "(";
    for (size_t i = 0; i < columns.size(); ++i) {
        if (i > 0) out += ", ";
        out += columns[i];
    }
    out += ") AS SELECT * FROM (VALUES ";

    if (rows.empty()) {
        out += "(";
        for (size_t i = 0; i < columns.size(); ++i) {
            if (i > 0) out += ", ";
            out += "NULL";
        }
        out += ")";
    } else {
        for (size_t i = 0; i < rows.size(); ++i) {
            if (i > 0) out += ", ";
            out += "(";
            const auto& row = rows[i];
            for (size_t j = 0; j < columns.size(); ++j) {
                if (j > 0) out += ", ";
                if (j < row.size()) out += row[j];
                else out += "NULL";
            }
            out += ")";
        }
    }

    out += ") AS t(";
    for (size_t i = 0; i < columns.size(); ++i) {
        if (i > 0) out += ", ";
        out += columns[i];
    }
    out += ")";
    if (rows.empty()) out += " WHERE 1=0";
    out += ";";
    return out;
}

} // namespace

std::vector<SqlViewDef> discover_sql_views(const Config& config) {
    std::vector<SqlViewDef> views;
    const auto data_root = std::filesystem::path(config.data.data_root);

    if (has_local_parquet(data_root)) {
        views.push_back(SqlViewDef{
            .dataset_id = "all_data",
            .view_name  = "all_data",
            .glob_path  = (data_root / "**/*.parquet").string(),
        });
    }

    auto kline_dir = std::filesystem::path(config.data.data_root) / "kline";
    if (has_local_parquet(kline_dir)) {
        views.push_back(SqlViewDef{
            .dataset_id = "kline",
            .view_name  = "kline",
            .glob_path  = (kline_dir / "**/*.parquet").string(),
        });
        // Convenience alias
        views.push_back(SqlViewDef{
            .dataset_id = "daily",
            .view_name  = "daily",
            .glob_path  = (kline_dir / "**/*.parquet").string(),
        });
    }

    // Sentiment layers: bronze (raw articles), silver (scored), gold (factors)
    auto sentiment_bronze_dir = data_root / "raw" / "sentiment";
    if (has_local_parquet(sentiment_bronze_dir)) {
        views.push_back(SqlViewDef{
            .dataset_id = "sentiment_bronze",
            .view_name  = "sentiment_bronze",
            .glob_path  = (sentiment_bronze_dir / "**/*.parquet").string(),
        });
    }

    auto sentiment_silver_dir = data_root / "sentiment" / "silver";
    if (has_local_parquet(sentiment_silver_dir)) {
        views.push_back(SqlViewDef{
            .dataset_id = "sentiment_silver",
            .view_name  = "sentiment_silver",
            .glob_path  = (sentiment_silver_dir / "**/*.parquet").string(),
        });
    }

    auto sentiment_gold_dir = data_root / "sentiment" / "gold";
    if (has_local_parquet(sentiment_gold_dir)) {
        views.push_back(SqlViewDef{
            .dataset_id = "sentiment_gold",
            .view_name  = "sentiment_gold",
            .glob_path  = (sentiment_gold_dir / "**/*.parquet").string(),
        });
    }

    return views;
}

std::string build_sql_init(const std::vector<SqlViewDef>& views) {
    std::string init_sql;
    for (const auto& v : views) {
        init_sql += "CREATE OR REPLACE VIEW " + v.view_name +
                    " AS SELECT * FROM read_parquet('" + sql_escape(v.glob_path) +
                    "', union_by_name=true);";
    }
    return init_sql;
}

std::string build_metadata_views_sql(const Config& config) {
    StoragePath paths(config.data.data_root);
    MetadataStore metadata(paths.metadata_db());

    std::vector<std::vector<std::string>> instrument_rows;
    auto instruments = metadata.get_all_instruments();
    instrument_rows.reserve(instruments.size());
    for (const auto& i : instruments) {
        instrument_rows.push_back({
            sql_string(i.symbol),
            sql_string(i.name),
            std::to_string(static_cast<int>(i.market)),
            sql_string(i.market_label()),
            std::to_string(static_cast<int>(i.board)),
            std::to_string(static_cast<int>(i.industry)),
            sql_string(format_date(i.list_date)),
            sql_date_or_null(i.delist_date),
            std::to_string(static_cast<int>(i.status)),
            std::to_string(i.total_shares),
            std::to_string(i.float_shares),
        });
    }

    return build_values_view_sql(
        "meta_instruments",
        {"symbol", "name", "market", "market_name", "board", "industry",
         "list_date", "delist_date", "status", "total_shares", "float_shares"},
        instrument_rows);
}

MetadataHealth assess_metadata_health(MetadataStore& metadata) {
    MetadataHealth h;
    h.instrument_count = metadata.get_all_instruments().size();
    h.ok = h.instrument_count > 0;
    return h;
}

} // namespace trade::cli
