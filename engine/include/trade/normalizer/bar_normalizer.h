#pragma once

#include "trade/model/bar.h"
#include <vector>

namespace trade {

class BarNormalizer {
public:
    // Normalize raw bars: sort by date, fill prev_close, compute VWAP
    static std::vector<Bar> normalize(std::vector<Bar> bars);

    // Fill missing prev_close from previous bar
    static void fill_prev_close(std::vector<Bar>& bars);

    // Compute VWAP = amount / volume
    static void compute_vwap(std::vector<Bar>& bars);

    // Sort by date ascending
    static void sort_by_date(std::vector<Bar>& bars);

    // Compute price limits from prev_close and board, detect limit hits
    static void compute_limits(std::vector<Bar>& bars, Board board);
};

} // namespace trade
