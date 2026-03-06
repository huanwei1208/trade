#pragma once

#include "trade/model/bar.h"
#include <vector>
#include <string>

namespace trade {

struct QualityReport {
    int total_bars = 0;
    int valid_bars = 0;
    int invalid_bars = 0;
    int missing_dates = 0;
    int duplicate_dates = 0;
    int price_anomalies = 0;   // e.g., close > limit_up or < limit_down
    int volume_anomalies = 0;  // e.g., volume = 0 on non-suspended day
    std::vector<std::string> warnings;

    bool is_clean() const { return invalid_bars == 0 && warnings.empty(); }
    double quality_score() const {
        return total_bars > 0
            ? static_cast<double>(valid_bars) / total_bars
            : 0.0;
    }
};

class DataValidator {
public:
    // Validate a series of bars
    static QualityReport validate(const std::vector<Bar>& bars);

    // Check for duplicate dates
    static int check_duplicates(const std::vector<Bar>& bars);

    // Check for missing trading days
    static int check_missing_dates(const std::vector<Bar>& bars,
                                    Date start, Date end);

    // Check price sanity (OHLC relationship, non-negative, etc.)
    static int check_price_sanity(const std::vector<Bar>& bars);

    // Check volume anomalies
    static int check_volume_anomalies(const std::vector<Bar>& bars);
};

} // namespace trade
