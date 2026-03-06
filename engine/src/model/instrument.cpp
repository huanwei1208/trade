#include "trade/model/instrument.h"
#include "trade/model/market.h"
#include <algorithm>
#include <numeric>

namespace trade {

int MarketSnapshot::up_count() const {
    int count = 0;
    for (const auto& [sym, bar] : bars) {
        if (bar.change_pct() > 0) ++count;
    }
    return count;
}

int MarketSnapshot::down_count() const {
    int count = 0;
    for (const auto& [sym, bar] : bars) {
        if (bar.change_pct() < 0) ++count;
    }
    return count;
}

int MarketSnapshot::limit_up_count() const {
    // Approximate: change > 9.5% (main board) suggests limit up
    int count = 0;
    for (const auto& [sym, bar] : bars) {
        if (bar.change_pct() > 0.095) ++count;
    }
    return count;
}

int MarketSnapshot::limit_down_count() const {
    int count = 0;
    for (const auto& [sym, bar] : bars) {
        if (bar.change_pct() < -0.095) ++count;
    }
    return count;
}

double MarketSnapshot::total_amount() const {
    double total = 0.0;
    for (const auto& [sym, bar] : bars) {
        total += bar.amount;
    }
    return total;
}

double MarketSnapshot::median_turnover() const {
    std::vector<double> turnovers;
    turnovers.reserve(bars.size());
    for (const auto& [sym, bar] : bars) {
        if (bar.turnover_rate > 0) {
            turnovers.push_back(bar.turnover_rate);
        }
    }
    if (turnovers.empty()) return 0.0;
    std::sort(turnovers.begin(), turnovers.end());
    size_t n = turnovers.size();
    return n % 2 == 0
        ? (turnovers[n/2 - 1] + turnovers[n/2]) / 2.0
        : turnovers[n/2];
}

void MarketPanel::add_series(const Symbol& sym, BarSeries&& bs) {
    if (std::find(symbols.begin(), symbols.end(), sym) == symbols.end()) {
        symbols.push_back(sym);
    }
    // Update dates set
    for (const auto& bar : bs.bars) {
        if (std::find(dates.begin(), dates.end(), bar.date) == dates.end()) {
            dates.push_back(bar.date);
        }
    }
    series[sym] = std::move(bs);
}

MarketSnapshot MarketPanel::snapshot(Date d) const {
    MarketSnapshot snap;
    snap.date = d;
    for (const auto& [sym, bs] : series) {
        for (const auto& bar : bs.bars) {
            if (bar.date == d) {
                snap.bars[sym] = bar;
                break;
            }
        }
    }
    return snap;
}

} // namespace trade
