#pragma once

#include "trade/common/types.h"
#include "trade/model/instrument.h"
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace trade {

// SQLite-backed metadata store.
// Keeps only the essential tables needed for data collection:
//   - instruments   : A-share instrument master data
//   - downloads     : per-symbol download tracking
//   - watermarks    : incremental ingestion high-water marks
class MetadataStore {
public:
    explicit MetadataStore(const std::string& db_path);
    ~MetadataStore();

    // ── Instrument master data ────────────────────────────────────────────
    void upsert_instrument(const Instrument& inst);
    std::optional<Instrument> get_instrument(const Symbol& symbol);
    std::vector<Instrument> get_all_instruments();
    std::vector<Instrument> get_instruments_by_market(Market market);
    std::vector<Instrument> get_instruments_by_industry(SWIndustry industry);

    // ── Download tracking ─────────────────────────────────────────────────
    void record_download(const Symbol& symbol, Date start, Date end,
                         int64_t row_count);
    std::optional<Date> last_download_date(const Symbol& symbol);
    std::vector<Symbol> symbols_needing_update(Date cutoff);

    // ── Event-time watermarks ─────────────────────────────────────────────
    // Meaning: max event date durably committed to storage.
    void upsert_watermark(const std::string& source,
                          const std::string& dataset,
                          const Symbol& symbol,
                          Date last_event_date,
                          const std::string& cursor_payload = "{}");
    std::optional<Date> last_watermark_date(const std::string& source,
                                            const std::string& dataset,
                                            const Symbol& symbol);

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace trade
