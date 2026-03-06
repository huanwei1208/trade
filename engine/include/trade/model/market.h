#pragma once

#include "trade/model/bar.h"
#include "trade/model/instrument.h"
#include <unordered_map>
#include <vector>

namespace trade {

// Cross-sectional snapshot of the market at a single date
struct MarketSnapshot {
    Date date;
    std::unordered_map<Symbol, Bar> bars;
    std::unordered_map<Symbol, Instrument> instruments;

    size_t stock_count() const { return bars.size(); }

    bool has(const Symbol& s) const { return bars.count(s) > 0; }

    const Bar& bar(const Symbol& s) const { return bars.at(s); }

    // Count stocks with positive/negative returns
    int up_count() const;
    int down_count() const;
    int limit_up_count() const;
    int limit_down_count() const;

    // Aggregate stats
    double total_amount() const;
    double median_turnover() const;
};

// Panel: all symbols across all dates
struct MarketPanel {
    std::vector<Date> dates;
    std::vector<Symbol> symbols;
    std::unordered_map<Symbol, BarSeries> series;

    void add_series(const Symbol& sym, BarSeries&& bs);
    MarketSnapshot snapshot(Date d) const;
};

} // namespace trade
