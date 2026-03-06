#include "trade/validator/data_validator.h"
#include "trade/common/time_utils.h"
#include <set>
#include <cmath>

namespace trade {

QualityReport DataValidator::validate(const std::vector<Bar>& bars) {
    QualityReport report;
    report.total_bars = static_cast<int>(bars.size());

    report.duplicate_dates = check_duplicates(bars);
    report.price_anomalies = check_price_sanity(bars);
    report.volume_anomalies = check_volume_anomalies(bars);
    report.invalid_bars = report.price_anomalies + report.volume_anomalies + report.duplicate_dates;
    report.valid_bars = report.total_bars - report.invalid_bars;

    if (report.duplicate_dates > 0) {
        report.warnings.push_back(
            "Found " + std::to_string(report.duplicate_dates) + " duplicate dates");
    }
    if (report.price_anomalies > 0) {
        report.warnings.push_back(
            "Found " + std::to_string(report.price_anomalies) + " price anomalies");
    }
    if (report.volume_anomalies > 0) {
        report.warnings.push_back(
            "Found " + std::to_string(report.volume_anomalies) + " volume anomalies");
    }

    return report;
}

int DataValidator::check_duplicates(const std::vector<Bar>& bars) {
    std::set<Date> seen;
    int dupes = 0;
    for (const auto& bar : bars) {
        if (!seen.insert(bar.date).second) {
            ++dupes;
        }
    }
    return dupes;
}

int DataValidator::check_missing_dates(const std::vector<Bar>& bars,
                                        Date start, Date end) {
    if (bars.empty()) return 0;
    auto trading_days = trading_days_between(start, end);
    std::set<Date> bar_dates;
    for (const auto& bar : bars) {
        bar_dates.insert(bar.date);
    }

    int missing = 0;
    for (const auto& td : trading_days) {
        if (bar_dates.find(td) == bar_dates.end()) {
            ++missing;
        }
    }
    return missing;
}

int DataValidator::check_price_sanity(const std::vector<Bar>& bars) {
    int anomalies = 0;
    for (const auto& bar : bars) {
        // OHLC relationship
        if (bar.high < bar.low) { ++anomalies; continue; }
        if (bar.high < bar.open || bar.high < bar.close) { ++anomalies; continue; }
        if (bar.low > bar.open || bar.low > bar.close) { ++anomalies; continue; }

        // Non-negative prices
        if (bar.open <= 0 || bar.high <= 0 || bar.low <= 0 || bar.close <= 0) {
            ++anomalies; continue;
        }

        // Extreme daily change (> 30% is suspicious even for STAR/ChiNext)
        if (bar.prev_close > 0) {
            double change = std::abs(bar.close - bar.prev_close) / bar.prev_close;
            if (change > 0.30) ++anomalies;
        }
    }
    return anomalies;
}

int DataValidator::check_volume_anomalies(const std::vector<Bar>& bars) {
    int anomalies = 0;
    for (const auto& bar : bars) {
        // Negative volume
        if (bar.volume < 0) { ++anomalies; continue; }
        // Negative amount
        if (bar.amount < 0) { ++anomalies; continue; }
        // Volume but no amount, or vice versa
        if (bar.volume > 0 && bar.amount <= 0) ++anomalies;
        if (bar.volume == 0 && bar.amount > 0) ++anomalies;
    }
    return anomalies;
}

} // namespace trade
