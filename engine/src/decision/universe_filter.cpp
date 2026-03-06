#include "trade/decision/universe_filter.h"

namespace trade {

// ---------------------------------------------------------------------------
// Constructors
// ---------------------------------------------------------------------------

UniverseFilter::UniverseFilter() : config_{} {}
UniverseFilter::UniverseFilter(Config cfg) : config_(cfg) {}

std::vector<Symbol> UniverseFilter::filter(
    const std::unordered_map<Symbol, Instrument>& all_instruments,
    const MarketSnapshot& snapshot,
    Date date,
    const std::unordered_map<Symbol, double>& adv_20d) const {

    last_stats_ = {};
    last_stats_.total_input = static_cast<int>(all_instruments.size());

    std::vector<Symbol> result;
    result.reserve(all_instruments.size());

    for (const auto& [symbol, inst] : all_instruments) {
        // 1. Suspended stocks
        if (config_.exclude_suspended && is_suspended(inst)) {
            last_stats_.rejected_suspended++;
            continue;
        }

        // 2. ST / *ST stocks
        if (config_.exclude_st && is_st(inst)) {
            last_stats_.rejected_st++;
            continue;
        }

        // 3. Limit-locked stocks (need bar data)
        if (config_.exclude_limit_locked && snapshot.has(symbol)) {
            const auto& bar = snapshot.bar(symbol);
            // Check both buy and sell locks -- reject if locked in either direction
            if (is_limit_locked(bar, inst, Side::kBuy)) {
                last_stats_.rejected_limit_locked++;
                continue;
            }
        }

        // 4. New stocks
        if (is_new_stock(inst, date)) {
            last_stats_.rejected_new_stock++;
            continue;
        }

        // 5. Low liquidity
        if (is_illiquid(symbol, adv_20d)) {
            last_stats_.rejected_illiquid++;
            continue;
        }

        // 6. Delisting risk
        if (config_.exclude_delisting && is_delisting(inst)) {
            last_stats_.rejected_delisting++;
            continue;
        }

        result.push_back(symbol);
    }

    last_stats_.total_output = static_cast<int>(result.size());
    return result;
}

bool UniverseFilter::is_suspended(const Instrument& inst) {
    return inst.status == TradingStatus::kSuspended;
}

bool UniverseFilter::is_st(const Instrument& inst) {
    return inst.is_st();
}

bool UniverseFilter::is_limit_locked(const Bar& bar, const Instrument& inst,
                                      Side side) const {
    if (bar.prev_close <= 0.0) return false;

    double pct = price_limit_pct(inst.board);
    double limit_up = bar.prev_close * (1.0 + pct);
    double limit_down = bar.prev_close * (1.0 - pct);

    if (side == Side::kBuy) {
        // Can't buy if stock is at limit-up (within proximity)
        return bar.close >= limit_up * (1.0 - config_.limit_proximity_pct);
    } else {
        // Can't sell if stock is at limit-down (within proximity)
        return bar.close <= limit_down * (1.0 + config_.limit_proximity_pct);
    }
}

bool UniverseFilter::is_new_stock(const Instrument& inst, Date date) const {
    return inst.days_listed(date) < config_.min_listing_days;
}

bool UniverseFilter::is_illiquid(const Symbol& symbol,
                                  const std::unordered_map<Symbol, double>& adv_20d) const {
    auto it = adv_20d.find(symbol);
    if (it == adv_20d.end()) return false;  // No data available, pass through
    return it->second < config_.min_adv_20d;
}

bool UniverseFilter::is_delisting(const Instrument& inst) {
    return inst.status == TradingStatus::kDelisting;
}

} // namespace trade
