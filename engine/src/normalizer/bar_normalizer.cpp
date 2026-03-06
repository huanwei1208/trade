#include "trade/normalizer/bar_normalizer.h"
#include <algorithm>

namespace trade {

std::vector<Bar> BarNormalizer::normalize(std::vector<Bar> bars) {
    sort_by_date(bars);
    fill_prev_close(bars);
    compute_vwap(bars);
    return bars;
}

void BarNormalizer::fill_prev_close(std::vector<Bar>& bars) {
    for (size_t i = 0; i < bars.size(); ++i) {
        if (bars[i].prev_close <= 0 && i > 0) {
            bars[i].prev_close = bars[i - 1].close;
        }
    }
}

void BarNormalizer::compute_vwap(std::vector<Bar>& bars) {
    for (auto& bar : bars) {
        if (bar.vwap <= 0 && bar.volume > 0) {
            bar.vwap = bar.amount / static_cast<double>(bar.volume);
        }
    }
}

void BarNormalizer::sort_by_date(std::vector<Bar>& bars) {
    std::sort(bars.begin(), bars.end(),
              [](const Bar& a, const Bar& b) { return a.date < b.date; });
}

void BarNormalizer::compute_limits(std::vector<Bar>& bars, Board board) {
    for (auto& bar : bars) {
        if (bar.prev_close <= 0) continue;
        double pct = price_limit_pct(board);
        bar.limit_up = bar.prev_close * (1.0 + pct);
        bar.limit_down = bar.prev_close * (1.0 - pct);
        // Round to 2 decimal places (A-share tick size = 0.01)
        bar.limit_up = static_cast<int>(bar.limit_up * 100 + 0.5) / 100.0;
        bar.limit_down = static_cast<int>(bar.limit_down * 100 + 0.5) / 100.0;
        bar.hit_limit_up = (bar.close >= bar.limit_up - 0.005);
        bar.hit_limit_down = (bar.close <= bar.limit_down + 0.005);
        bar.board = board;
    }
}

} // namespace trade
