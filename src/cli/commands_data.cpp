#include "trade/cli/commands.h"

#include "trade/cli/shared.h"
#include "trade/common/time_utils.h"
#include "trade/storage/duck_store.h"
#include "trade/storage/google_drive_sync.h"
#include "trade/storage/metadata_store.h"
#include "trade/storage/parquet_reader.h"
#include "trade/storage/storage_path.h"
#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>
#include <spdlog/spdlog.h>

namespace trade::cli {
namespace {

bool executable_exists(const std::string& path) {
    if (path.empty()) return false;
    std::error_code ec;
    return std::filesystem::exists(path, ec) && std::filesystem::is_regular_file(path, ec);
}

std::string shell_quote(const std::string& s) {
    std::string out = "'";
    for (char c : s) {
        if (c == '\'') out += "'\\''";
        else out.push_back(c);
    }
    out += "'";
    return out;
}

std::string find_duckdb_cli() {
    if (const char* env_duckdb = std::getenv("TRADE_DUCKDB_BIN")) {
        if (executable_exists(env_duckdb)) return env_duckdb;
    }
    if (std::system("which duckdb > /dev/null 2>&1") == 0) {
        return "duckdb";
    }
#ifdef TRADE_SOURCE_DIR
    const std::string root = TRADE_SOURCE_DIR;
    const std::vector<std::string> candidates = {
        root + "/build/linux/vendor/duckdb/duckdb",
        root + "/build/default/vendor/duckdb/duckdb",
        root + "/build/debug/vendor/duckdb/duckdb",
        root + "/vendor/duckdb/build/release/duckdb",
    };
    for (const auto& c : candidates) {
        if (executable_exists(c)) return c;
    }
#endif
    return "";
}

int run_embedded_sql_shell(const std::string& init_sql) {
    std::cout << "DuckDB CLI not found, using embedded SQL shell.\n"
              << "Type SQL and press Enter, type .exit to quit.\n\n";
    try {
        trade::DuckStore db;
        if (!init_sql.empty()) db.execute(init_sql);

        std::string line;
        while (true) {
            std::cout << "duckdb> " << std::flush;
            if (!std::getline(std::cin, line)) break;
            if (line == ".exit" || line == ".quit" || line == "exit" || line == "quit") break;
            if (line.empty()) continue;

            auto rows = db.query(line);
            std::cout << "rows: " << rows.size() << "\n";
            for (const auto& row : rows) {
                for (size_t i = 0; i < row.size(); ++i) {
                    if (i > 0) std::cout << "\t";
                    std::cout << row[i];
                }
                std::cout << "\n";
            }
        }
        return 0;
    } catch (const std::exception& e) {
        spdlog::error("Embedded SQL shell failed: {}", e.what());
        return 1;
    }
}

} // namespace

int cmd_verify(const CliArgs& args, const trade::Config& config) {
    bool ok_local = false;
    bool ok_cloud = false;
    bool ok_meta = false;
    bool ok_sql = false;

    trade::StoragePath paths(config.data.data_root);
    trade::MetadataStore metadata(paths.metadata_db());

    std::cout << "=== Verify Data Pipeline ===\n";

    // 1) Local check: count instruments
    auto instruments = metadata.get_all_instruments();
    ok_local = !instruments.empty() || !args.symbol.empty();
    if (!args.symbol.empty()) {
        auto bars = load_bars(args.symbol, config);
        ok_local = !bars.empty();
        std::cout << "[Local] symbol=" << args.symbol
                  << " rows=" << bars.size()
                  << " -> " << (ok_local ? "OK" : "FAIL") << "\n";
    } else {
        std::cout << "[Local] instruments=" << instruments.size()
                  << " -> " << (ok_local ? "OK" : "FAIL") << "\n";
    }

    // 2) Cloud check (optional)
    const bool cloud_mode = config.storage.enabled &&
        config.storage.backend == "google_drive";
    if (cloud_mode) {
        trade::GoogleDriveSync client({
            .service_account_json_path = config.storage.google_drive_key_file,
            .root_folder_id = config.storage.google_drive_folder_id,
            .timeout_ms = config.storage.google_drive_timeout_ms,
            .retry_count = config.storage.google_drive_retry_count,
        });
        auto ts = std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
        std::string probe = "_health/verify_" + std::to_string(ts) + ".txt";
        const std::string msg = "trade-cloud-verify";
        std::vector<uint8_t> up(msg.begin(), msg.end());
        std::vector<uint8_t> down;
        bool uploaded = client.upload_bytes(probe, up);
        bool downloaded = uploaded && client.download_bytes(probe, &down);
        ok_cloud = downloaded && (std::string(down.begin(), down.end()) == msg);
        std::cout << "[Cloud] probe=" << probe
                  << " uploaded=" << (uploaded ? "yes" : "no")
                  << " downloaded=" << (downloaded ? "yes" : "no")
                  << " -> " << (ok_cloud ? "OK" : "FAIL") << "\n";
    } else {
        ok_cloud = true;
        std::cout << "[Cloud] skipped (storage backend is local/disabled)\n";
    }

    // 3) Metadata check
    auto mh = assess_metadata_health(metadata);
    ok_meta = mh.ok;
    std::cout << "[Meta] instruments=" << mh.instrument_count
              << " -> " << (ok_meta ? "OK" : "FAIL") << "\n";

    // 4) SQL check (embedded DuckDB, no external CLI dependency)
    auto views = discover_sql_views(config);
    if (!views.empty()) {
        try {
            trade::DuckStore db;
            std::string init_sql = build_sql_init(views) + build_metadata_views_sql(config);
            db.execute(init_sql);
            auto rows = db.query("SELECT count(*) FROM " + views.front().view_name + ";");
            ok_sql = !rows.empty();
            std::cout << "[SQL] view=" << views.front().view_name
                      << " -> " << (ok_sql ? "OK" : "FAIL") << "\n";
        } catch (const std::exception& e) {
            ok_sql = false;
            std::cout << "[SQL] embedded duckdb query failed: " << e.what() << " -> FAIL\n";
        }
    } else {
        ok_sql = false;
        std::cout << "[SQL] no dataset views found -> FAIL\n";
    }

    bool pass = ok_local && ok_cloud && ok_meta && ok_sql;
    std::cout << "Result: " << (pass ? "PASS" : "FAIL") << "\n";
    return pass ? 0 : 1;
}

// ============================================================================
// collect — DEPRECATED: use Python/akshare pipeline instead
// ============================================================================
int cmd_collect(const CliArgs& /*args*/, const trade::Config& /*config*/) {
    std::cerr << "[DEPRECATED] The C++ collect command has been removed.\n"
              << "Use: uv run python python/scripts/run_collector.py collect --symbol CODE --start YYYY-MM-DD\n"
              << "Or:  uv run python python/scripts/run_collector.py update-all\n";
    return 1;
}

// ============================================================================
// silver — DEPRECATED: data normalisation is now handled by the Python pipeline
// ============================================================================
int cmd_silver(const CliArgs& /*args*/, const trade::Config& /*config*/) {
    std::cerr << "[DEPRECATED] The C++ silver command has been removed.\n"
              << "Data ingestion (raw + normalisation) is now handled by:\n"
              << "  uv run python python/scripts/run_collector.py update-all\n";
    return 1;
}

// ============================================================================
// cleanup
// ============================================================================
int cmd_cleanup(const CliArgs& args, const trade::Config& config) {
    const std::string action = args.action.empty() ? "audit" : args.action;

    if (action != "audit" && action != "apply") {
        spdlog::error("Unsupported cleanup action '{}'. Use audit|apply", action);
        return 1;
    }

    const bool apply = (action == "apply");
    const std::string mode = apply ? "apply" : "audit";

    trade::StoragePath paths(config.data.data_root);
    trade::MetadataStore metadata(paths.metadata_db());

    auto instruments = metadata.get_all_instruments();
    std::cout << "=== Data Cleanup (" << mode << ") ===\n"
              << "Data root: " << config.data.data_root << "\n"
              << "Instruments: " << instruments.size() << "\n";

    if (!apply) {
        std::cout << "Dry run only. Use: trade_cli cleanup --action apply --config <path>\n";
    }
    return 0;
}


// ============================================================================
// info
// ============================================================================
int cmd_info(const CliArgs& args, const trade::Config& config) {
    if (!args.symbol.empty()) {
        auto bars = load_bars(args.symbol, config);
        std::cout << "Symbol: " << args.symbol << "\nBars: " << bars.size() << std::endl;
        if (!bars.empty()) {
            std::cout << "Range: " << trade::format_date(bars.front().date)
                     << " to " << trade::format_date(bars.back().date) << std::endl;
            std::cout << "Last close: " << std::fixed << std::setprecision(2)
                     << bars.back().close << std::endl;
        }
    } else {
        std::cout << "Data root: " << config.data.data_root << "\nProvider: "
                 << args.provider << std::endl;
    }
    return 0;
}

// ============================================================================
// sql — launch DuckDB CLI with data directory pre-configured
// ============================================================================
int cmd_sql(const CliArgs& args, const trade::Config& config) {
    const std::string duckdb_cli = find_duckdb_cli();

    const bool cloud_mode = config.storage.enabled &&
        config.storage.backend == "google_drive";

    // Cloud backflow: hydrate requested file/symbol into local cache before DuckDB starts.
    bool symbol_hydrated = false;
    if (cloud_mode) {
        if (!args.file.empty() && !std::filesystem::exists(args.file)) {
            auto t = trade::ParquetReader::read_table(args.file);
            if (!t) {
                spdlog::warn("Failed to hydrate --file from cloud: {}", args.file);
            }
        }
        if (!args.symbol.empty()) {
            auto hydrated = load_bars(args.symbol, config);
            symbol_hydrated = !hydrated.empty();
            if (!symbol_hydrated) {
                spdlog::warn("No local/cloud data found for symbol {}", args.symbol);
            }
        }
    }

    // Build init SQL: create views from dataset catalog.
    auto views = discover_sql_views(config);
    std::string init_sql = build_sql_init(views);
    init_sql += build_metadata_views_sql(config);

    auto has_dataset = [&](const std::string& dataset_id) {
        return std::any_of(views.begin(), views.end(), [&](const SqlViewDef& v) {
            return v.dataset_id == dataset_id;
        });
    };

    // If a specific file is given, also create a 'data' view
    bool data_view_ready = false;
    if (!args.file.empty()) {
        if (std::filesystem::exists(args.file)) {
            init_sql += "CREATE OR REPLACE VIEW data AS SELECT * FROM read_parquet('" +
                        sql_escape(args.file) + "', union_by_name=true);";
            data_view_ready = true;
        }
    } else if (!args.symbol.empty()) {
        if (!cloud_mode || symbol_hydrated) {
            if (has_dataset("kline") || has_dataset("daily")) {
                init_sql += "CREATE OR REPLACE VIEW data AS "
                            "SELECT * FROM kline WHERE symbol='" +
                            sql_escape(args.symbol) + "';";
                data_view_ready = true;
            }
        }
    }

    std::cout << "Starting DuckDB SQL shell...\n"
              << "Pre-configured views from catalog:\n";
    for (const auto& v : views) {
        std::cout << "  " << v.view_name << "  (" << v.dataset_id << ")\n";
    }
    if (data_view_ready) {
        std::cout << "  data   - specific file/symbol data\n";
    }
    if (views.empty() && !data_view_ready) {
        std::cout << "  (no local parquet found yet; run collect first)\n";
    }
    std::cout << "\nExample queries:\n";
    if (has_dataset("kline") || has_dataset("daily")) {
        std::cout << "  SELECT * FROM kline WHERE symbol='600000.SH' ORDER BY date;\n"
                  << "  SELECT symbol, count(*) FROM kline GROUP BY symbol;\n";
    }
    if (has_dataset("sentiment_bronze")) {
        std::cout << "  SELECT date, source, title FROM sentiment_bronze ORDER BY date DESC LIMIT 20;\n"
                  << "  SELECT date, source, count(*) AS articles FROM sentiment_bronze GROUP BY date, source ORDER BY date DESC;\n";
    }
    if (has_dataset("sentiment_silver")) {
        std::cout << "  SELECT * FROM sentiment_silver ORDER BY date DESC LIMIT 20;\n"
                  << "  SELECT date, symbol, sentiment_score FROM sentiment_silver WHERE symbol='600000.SH' ORDER BY date;\n";
    }
    if (has_dataset("sentiment_gold")) {
        std::cout << "  SELECT * FROM sentiment_gold ORDER BY date DESC LIMIT 20;\n"
                  << "  SELECT date, symbol, sentiment_score FROM sentiment_gold ORDER BY date DESC, sentiment_score DESC;\n";
    }
    if (has_dataset("all_data")) {
        std::cout << "  SELECT * FROM all_data LIMIT 20;\n";
    } else if (!views.empty()) {
        std::cout << "  SELECT * FROM " << views.front().view_name << " LIMIT 20;\n";
    } else {
        std::cout << "  -- no dataset views yet; run collect first\n";
    }
    if (data_view_ready) {
        std::cout << "  SELECT * FROM data LIMIT 20;\n";
    }
    std::cout << "  SELECT * FROM meta_instruments;\n";
    std::cout << std::endl;

    if (cloud_mode) {
        std::cout << "Cloud mode enabled: DuckDB sees local + hydrated cache partitions.\n"
                  << "Tip: use --symbol to pre-hydrate one symbol from Google Drive cloud.\n"
                  << std::endl;
    }

    if (duckdb_cli.empty()) {
        return run_embedded_sql_shell(init_sql);
    }

    // Launch duckdb with init commands
    std::string cmd = shell_quote(duckdb_cli) + " -init /dev/null -cmd \"" + init_sql + "\"";
    return std::system(cmd.c_str());
}

} // namespace trade::cli
