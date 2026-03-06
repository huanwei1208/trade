#include "trade/storage/metadata_store.h"
#include "trade/common/time_utils.h"
#include <filesystem>
#include <spdlog/spdlog.h>
#include <sqlite3.h>
#include <stdexcept>

namespace trade {

namespace {

std::optional<Date> read_date_column(sqlite3_stmt* stmt, int col) {
    auto txt = sqlite3_column_text(stmt, col);
    if (!txt) return std::nullopt;
    return parse_date(reinterpret_cast<const char*>(txt));
}

void bind_date_or_null(sqlite3_stmt* stmt, int col, std::optional<Date> d) {
    if (d) {
        std::string v = format_date(*d);
        sqlite3_bind_text(stmt, col, v.c_str(), -1, SQLITE_TRANSIENT);
    } else {
        sqlite3_bind_null(stmt, col);
    }
}

} // namespace

struct MetadataStore::Impl {
    sqlite3* db = nullptr;

    ~Impl() {
        if (db) sqlite3_close(db);
    }

    void exec(const std::string& sql) {
        char* err = nullptr;
        int rc = sqlite3_exec(db, sql.c_str(), nullptr, nullptr, &err);
        if (rc != SQLITE_OK) {
            std::string msg = err ? err : "unknown error";
            sqlite3_free(err);
            throw std::runtime_error("SQL error: " + msg);
        }
    }
};

MetadataStore::MetadataStore(const std::string& db_path) : impl_(std::make_unique<Impl>()) {
    auto parent = std::filesystem::path(db_path).parent_path();
    if (!parent.empty() && db_path != ":memory:") {
        std::filesystem::create_directories(parent);
    }
    int rc = sqlite3_open(db_path.c_str(), &impl_->db);
    if (rc != SQLITE_OK) {
        throw std::runtime_error("Failed to open database: " + db_path);
    }

    impl_->exec(R"(
        CREATE TABLE IF NOT EXISTS instruments (
            symbol TEXT PRIMARY KEY,
            name TEXT,
            market INTEGER,
            board INTEGER,
            industry INTEGER,
            list_date TEXT,
            delist_date TEXT,
            status INTEGER,
            total_shares INTEGER DEFAULT 0,
            float_shares INTEGER DEFAULT 0,
            market_name TEXT NOT NULL DEFAULT ''
        )
    )");

    // Schema migration: add columns if missing (for existing DBs)
    sqlite3_exec(impl_->db,
                 "ALTER TABLE instruments ADD COLUMN total_shares INTEGER DEFAULT 0",
                 nullptr, nullptr, nullptr);
    sqlite3_exec(impl_->db,
                 "ALTER TABLE instruments ADD COLUMN float_shares INTEGER DEFAULT 0",
                 nullptr, nullptr, nullptr);
    sqlite3_exec(impl_->db,
                 "ALTER TABLE instruments ADD COLUMN market_name TEXT NOT NULL DEFAULT ''",
                 nullptr, nullptr, nullptr);
    impl_->exec(R"(
        UPDATE instruments
           SET market_name = CASE market
                                WHEN 0 THEN 'Shanghai'
                                WHEN 1 THEN 'Shenzhen'
                                WHEN 2 THEN 'Beijing'
                                WHEN 3 THEN 'Hong Kong'
                                WHEN 4 THEN 'US'
                                WHEN 5 THEN 'Crypto'
                                ELSE 'Unknown'
                             END
         WHERE market_name = ''
    )");

    impl_->exec(R"(
        CREATE TABLE IF NOT EXISTS downloads (
            symbol TEXT,
            start_date TEXT,
            end_date TEXT,
            row_count INTEGER,
            downloaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, end_date)
        )
    )");

    impl_->exec(R"(
        CREATE TABLE IF NOT EXISTS watermarks (
            source TEXT NOT NULL,
            dataset TEXT NOT NULL,
            symbol TEXT NOT NULL,
            last_event_date TEXT NOT NULL,
            cursor_payload TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (source, dataset, symbol)
        )
    )");

    impl_->exec("CREATE INDEX IF NOT EXISTS idx_downloads_symbol_end ON downloads(symbol, end_date)");
    impl_->exec("CREATE INDEX IF NOT EXISTS idx_watermarks_lookup ON watermarks(source, dataset, symbol)");

    spdlog::debug("MetadataStore initialized at {}", db_path);
}

MetadataStore::~MetadataStore() = default;

// ── helpers ──────────────────────────────────────────────────────────────────

namespace {

Instrument read_instrument_row(sqlite3_stmt* stmt) {
    Instrument inst;
    inst.symbol   = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
    inst.name     = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
    inst.market   = static_cast<Market>(sqlite3_column_int(stmt, 2));
    inst.board    = static_cast<Board>(sqlite3_column_int(stmt, 3));
    inst.industry = static_cast<SWIndustry>(sqlite3_column_int(stmt, 4));
    inst.list_date = parse_date(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5)));
    if (auto delist = sqlite3_column_text(stmt, 6)) {
        inst.delist_date = parse_date(reinterpret_cast<const char*>(delist));
    }
    inst.status      = static_cast<TradingStatus>(sqlite3_column_int(stmt, 7));
    inst.total_shares = sqlite3_column_int64(stmt, 8);
    inst.float_shares = sqlite3_column_int64(stmt, 9);
    if (sqlite3_column_count(stmt) > 10 && sqlite3_column_text(stmt, 10)) {
        inst.market_name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10));
    }
    return inst;
}

} // namespace

// ── Instrument ────────────────────────────────────────────────────────────────

void MetadataStore::upsert_instrument(const Instrument& inst) {
    const char* sql = R"(
        INSERT OR REPLACE INTO instruments
        (symbol, name, market, board, industry, list_date, delist_date, status,
         total_shares, float_shares, market_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(impl_->db, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        spdlog::error("Failed to prepare upsert_instrument: {}", sqlite3_errmsg(impl_->db));
        return;
    }

    std::string list_str = format_date(inst.list_date);
    sqlite3_bind_text(stmt, 1, inst.symbol.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, inst.name.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 3, static_cast<int>(inst.market));
    sqlite3_bind_int(stmt, 4, static_cast<int>(inst.board));
    sqlite3_bind_int(stmt, 5, static_cast<int>(inst.industry));
    sqlite3_bind_text(stmt, 6, list_str.c_str(), -1, SQLITE_TRANSIENT);
    bind_date_or_null(stmt, 7, inst.delist_date);
    sqlite3_bind_int(stmt, 8, static_cast<int>(inst.status));
    sqlite3_bind_int64(stmt, 9, inst.total_shares);
    sqlite3_bind_int64(stmt, 10, inst.float_shares);
    const std::string mn = inst.market_name.empty()
        ? market_name_from_enum(inst.market)
        : inst.market_name;
    sqlite3_bind_text(stmt, 11, mn.c_str(), -1, SQLITE_TRANSIENT);

    if (sqlite3_step(stmt) != SQLITE_DONE) {
        spdlog::error("Failed to upsert instrument {}: {}",
                      inst.symbol, sqlite3_errmsg(impl_->db));
    }
    sqlite3_finalize(stmt);
}

std::optional<Instrument> MetadataStore::get_instrument(const Symbol& symbol) {
    const char* sql = "SELECT * FROM instruments WHERE symbol = ?";
    sqlite3_stmt* stmt = nullptr;
    sqlite3_prepare_v2(impl_->db, sql, -1, &stmt, nullptr);
    sqlite3_bind_text(stmt, 1, symbol.c_str(), -1, SQLITE_TRANSIENT);

    if (sqlite3_step(stmt) == SQLITE_ROW) {
        auto inst = read_instrument_row(stmt);
        sqlite3_finalize(stmt);
        return inst;
    }
    sqlite3_finalize(stmt);
    return std::nullopt;
}

std::vector<Instrument> MetadataStore::get_all_instruments() {
    std::vector<Instrument> result;
    const char* sql = "SELECT * FROM instruments";
    sqlite3_stmt* stmt = nullptr;
    sqlite3_prepare_v2(impl_->db, sql, -1, &stmt, nullptr);
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        result.push_back(read_instrument_row(stmt));
    }
    sqlite3_finalize(stmt);
    return result;
}

std::vector<Instrument> MetadataStore::get_instruments_by_market(Market market) {
    auto all = get_all_instruments();
    std::vector<Instrument> out;
    for (auto& i : all) {
        if (i.market == market) out.push_back(std::move(i));
    }
    return out;
}

std::vector<Instrument> MetadataStore::get_instruments_by_industry(SWIndustry industry) {
    auto all = get_all_instruments();
    std::vector<Instrument> out;
    for (auto& i : all) {
        if (i.industry == industry) out.push_back(std::move(i));
    }
    return out;
}

// ── Downloads ─────────────────────────────────────────────────────────────────

void MetadataStore::record_download(const Symbol& symbol, Date start, Date end,
                                    int64_t row_count) {
    const char* sql = R"(
        INSERT OR REPLACE INTO downloads (symbol, start_date, end_date, row_count)
        VALUES (?, ?, ?, ?)
    )";
    sqlite3_stmt* stmt = nullptr;
    sqlite3_prepare_v2(impl_->db, sql, -1, &stmt, nullptr);
    std::string start_s = format_date(start);
    std::string end_s   = format_date(end);
    sqlite3_bind_text(stmt, 1, symbol.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, start_s.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, end_s.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 4, row_count);
    sqlite3_step(stmt);
    sqlite3_finalize(stmt);
}

std::optional<Date> MetadataStore::last_download_date(const Symbol& symbol) {
    const char* sql = "SELECT MAX(end_date) FROM downloads WHERE symbol = ?";
    sqlite3_stmt* stmt = nullptr;
    sqlite3_prepare_v2(impl_->db, sql, -1, &stmt, nullptr);
    sqlite3_bind_text(stmt, 1, symbol.c_str(), -1, SQLITE_TRANSIENT);
    if (sqlite3_step(stmt) == SQLITE_ROW && sqlite3_column_text(stmt, 0)) {
        auto date = parse_date(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)));
        sqlite3_finalize(stmt);
        return date;
    }
    sqlite3_finalize(stmt);
    return std::nullopt;
}

std::vector<Symbol> MetadataStore::symbols_needing_update(Date cutoff) {
    std::vector<Symbol> result;
    std::string cutoff_str = format_date(cutoff);
    const char* sql = R"(
        SELECT i.symbol FROM instruments i
        LEFT JOIN (
            SELECT symbol, MAX(end_date) as last_date
            FROM downloads GROUP BY symbol
        ) d ON i.symbol = d.symbol
        WHERE d.last_date IS NULL OR d.last_date < ?
    )";
    sqlite3_stmt* stmt = nullptr;
    sqlite3_prepare_v2(impl_->db, sql, -1, &stmt, nullptr);
    sqlite3_bind_text(stmt, 1, cutoff_str.c_str(), -1, SQLITE_TRANSIENT);
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        result.emplace_back(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)));
    }
    sqlite3_finalize(stmt);
    return result;
}

// ── Watermarks ────────────────────────────────────────────────────────────────

void MetadataStore::upsert_watermark(const std::string& source,
                                     const std::string& dataset,
                                     const Symbol& symbol,
                                     Date last_event_date,
                                     const std::string& cursor_payload) {
    const char* sql = R"(
        INSERT INTO watermarks (source, dataset, symbol, last_event_date, cursor_payload, updated_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(source, dataset, symbol)
        DO UPDATE SET
            last_event_date = excluded.last_event_date,
            cursor_payload  = excluded.cursor_payload,
            updated_at      = CURRENT_TIMESTAMP
    )";
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(impl_->db, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        spdlog::error("Failed to prepare upsert_watermark: {}", sqlite3_errmsg(impl_->db));
        return;
    }
    std::string date_s = format_date(last_event_date);
    sqlite3_bind_text(stmt, 1, source.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, dataset.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, symbol.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, date_s.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, cursor_payload.c_str(), -1, SQLITE_TRANSIENT);
    if (sqlite3_step(stmt) != SQLITE_DONE) {
        spdlog::error("Failed to upsert watermark {}/{}/{}: {}",
                      source, dataset, symbol, sqlite3_errmsg(impl_->db));
    }
    sqlite3_finalize(stmt);
}

std::optional<Date> MetadataStore::last_watermark_date(const std::string& source,
                                                       const std::string& dataset,
                                                       const Symbol& symbol) {
    const char* sql = R"(
        SELECT last_event_date FROM watermarks
        WHERE source = ? AND dataset = ? AND symbol = ?
    )";
    sqlite3_stmt* stmt = nullptr;
    sqlite3_prepare_v2(impl_->db, sql, -1, &stmt, nullptr);
    sqlite3_bind_text(stmt, 1, source.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, dataset.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, symbol.c_str(), -1, SQLITE_TRANSIENT);
    std::optional<Date> out;
    if (sqlite3_step(stmt) == SQLITE_ROW && sqlite3_column_text(stmt, 0)) {
        out = parse_date(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)));
    }
    sqlite3_finalize(stmt);
    return out;
}

} // namespace trade
