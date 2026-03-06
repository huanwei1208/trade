#pragma once

#include "trade/common/types.h"
#include "trade/model/bar.h"
#include "trade/model/instrument.h"
#include "trade/model/market.h"

#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace trade {

// ============================================================================
// UniverseFilter: tradable universe construction
// ============================================================================
// Filters the full A-share stock pool (~5000 stocks) down to a tradable
// universe of ~1500-2500 names by applying a cascade of exclusion rules.
//
// Exclusion rules (applied in order):
//   1. Suspended stocks          -- TradingStatus != kNormal
//   2. ST / *ST stocks           -- risk_warning flag
//   3. Limit-locked stocks       -- can't buy at limit-up, can't sell at
//                                   limit-down (direction-aware)
//   4. New stocks                -- < 120 trading days since listing
//   5. Low liquidity stocks      -- 20-day average daily volume < threshold
//   6. Delisting-risk stocks     -- in delisting consolidation period
//
// Usage:
//   UniverseFilter filter;
//   auto tradable = filter.filter(all_instruments, snapshot, today);
//
class UniverseFilter {
public:
    // -----------------------------------------------------------------------
    // Configuration
    // -----------------------------------------------------------------------
    struct Config {
        int min_listing_days = 120;              // exclude stocks listed < N days
        double min_adv_20d = 5'000'000.0;        // min 20d ADV in yuan (5M default)
        bool exclude_st = true;                  // exclude ST / *ST
        bool exclude_suspended = true;           // exclude suspended stocks
        bool exclude_limit_locked = true;        // exclude limit-up (buy) / limit-down (sell)
        bool exclude_delisting = true;           // exclude delisting consolidation
        double limit_proximity_pct = 0.005;      // within 0.5% of limit counts as locked
    };

    UniverseFilter();
    explicit UniverseFilter(Config cfg);

    // -----------------------------------------------------------------------
    // Core interface
    // -----------------------------------------------------------------------

    // Filter the full instrument list to a tradable universe.
    //   all_instruments: full instrument metadata indexed by symbol
    //   snapshot:        today's market snapshot (for price limit and volume checks)
    //   date:            current date (for listing age calculation)
    //   adv_20d:         pre-computed 20-day average daily volume per symbol (yuan)
    // Returns: vector of tradable Symbol identifiers.
    std::vector<Symbol> filter(
        const std::unordered_map<Symbol, Instrument>& all_instruments,
        const MarketSnapshot& snapshot,
        Date date,
        const std::unordered_map<Symbol, double>& adv_20d = {}) const;

    // -----------------------------------------------------------------------
    // Individual rule checks (can be used standalone for diagnostics)
    // -----------------------------------------------------------------------

    // Is the stock suspended?
    static bool is_suspended(const Instrument& inst);

    // Is the stock ST or *ST?
    static bool is_st(const Instrument& inst);

    // Is the stock limit-locked (can't buy at limit-up, can't sell at limit-down)?
    // side: kBuy checks limit-up lock; kSell checks limit-down lock.
    bool is_limit_locked(const Bar& bar, const Instrument& inst, Side side) const;

    // Is the stock too new (< min_listing_days)?
    bool is_new_stock(const Instrument& inst, Date date) const;

    // Does the stock fail the liquidity filter?
    bool is_illiquid(const Symbol& symbol,
                     const std::unordered_map<Symbol, double>& adv_20d) const;

    // Is the stock in delisting consolidation?
    static bool is_delisting(const Instrument& inst);

    // -----------------------------------------------------------------------
    // Diagnostics: per-rule rejection counts from the last filter() call
    // -----------------------------------------------------------------------
    struct FilterStats {
        int total_input = 0;
        int total_output = 0;
        int rejected_suspended = 0;
        int rejected_st = 0;
        int rejected_limit_locked = 0;
        int rejected_new_stock = 0;
        int rejected_illiquid = 0;
        int rejected_delisting = 0;
    };

    // Retrieve statistics from the last filter() call.
    const FilterStats& last_stats() const { return last_stats_; }

    const Config& config() const { return config_; }
    void set_config(const Config& cfg) { config_ = cfg; }

private:
    Config config_;
    mutable FilterStats last_stats_ = {};
};

} // namespace trade
