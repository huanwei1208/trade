#include "trade/features/calendar.h"
#include <algorithm>
#include <cmath>

namespace trade {

// ============================================================================
// CalendarFlags for a single date
// ============================================================================

CalendarMacroCalculator::CalendarFlags CalendarMacroCalculator::calendar_flags(Date d) {
    CalendarFlags flags;

    // Holiday windows (from time_utils)
    flags.is_spring_festival = is_spring_festival_window(d) ? 1.0 : 0.0;
    flags.is_national_day = is_national_day_window(d) ? 1.0 : 0.0;
    flags.is_two_sessions = is_two_sessions_window(d) ? 1.0 : 0.0;

    // Month end (last 3 trading days)
    flags.is_month_end = trade::is_month_end(d) ? 1.0 : 0.0;

    // Day of week: Mon=0.0, Tue=0.25, Wed=0.5, Thu=0.75, Fri=1.0
    int dow = day_of_week(d);  // 0=Sun, 1=Mon, ..., 6=Sat
    // Map Monday(1)=0.0, Tuesday(2)=0.25, ..., Friday(5)=1.0
    if (dow >= 1 && dow <= 5) {
        flags.day_of_week = static_cast<double>(dow - 1) / 4.0;
    } else {
        flags.day_of_week = 0.0;
    }

    // Day of month fraction: approximate as day / 22 (avg trading days/month)
    int day = date_day(d);
    [[maybe_unused]] int month = date_month(d);
    // Approximate total trading days in month as ~22
    flags.day_of_month_frac = std::min(1.0, static_cast<double>(day) / 22.0);

    // Quarter end and year start
    flags.is_quarter_end = CalendarMacroCalculator::is_quarter_end(d) ? 1.0 : 0.0;
    flags.is_year_start = CalendarMacroCalculator::is_year_start(d) ? 1.0 : 0.0;

    return flags;
}

bool CalendarMacroCalculator::is_quarter_end(Date d) {
    int month = date_month(d);
    int day = date_day(d);

    // Quarter-end months: 3, 6, 9, 12
    // Check if within last 5 trading days of quarter-end month
    if (month == 3 || month == 6 || month == 9 || month == 12) {
        // Approximate: last 5 calendar days that could be trading days
        // In practice, if day >= 25 it is likely within last 5 trading days
        if (day >= 25) return true;
    }
    return false;
}

bool CalendarMacroCalculator::is_year_start(Date d) {
    int month = date_month(d);
    int day = date_day(d);

    // First 5 trading days of the year: January, first ~8 calendar days
    // (accounting for possible holidays around New Year)
    if (month == 1 && day <= 10) return true;
    return false;
}

// ============================================================================
// Market-level series computation
// ============================================================================

Eigen::VectorXd CalendarMacroCalculator::market_return_series(
    const std::vector<BarSeries>& series, int max_len) {
    Eigen::VectorXd mkt = Eigen::VectorXd::Zero(max_len);
    Eigen::VectorXd count = Eigen::VectorXd::Zero(max_len);

    for (const auto& bs : series) {
        int n = static_cast<int>(bs.size());
        if (n < 2) continue;
        int offset = max_len - n;

        for (int i = 1; i < n; ++i) {
            double prev = bs[i - 1].close;
            if (prev > 0 && (offset + i) >= 0) {
                double ret = bs[i].close / prev - 1.0;
                if (!std::isnan(ret)) {
                    mkt(offset + i) += ret;
                    count(offset + i) += 1.0;
                }
            }
        }
    }

    for (int i = 0; i < max_len; ++i) {
        mkt(i) = (count(i) > 0) ? mkt(i) / count(i) : 0.0;
    }
    return mkt;
}

Eigen::VectorXd CalendarMacroCalculator::market_volatility_series(
    const std::vector<BarSeries>& series, int vol_window, int max_len) {
    // Compute average realized vol across stocks at each date
    // First, compute market returns, then rolling std of market returns
    auto mkt_ret = market_return_series(series, max_len);
    return rolling_std(mkt_ret, vol_window);
}

double CalendarMacroCalculator::vol_percentile(
    const Eigen::VectorXd& vol_history, int lookback) {
    int n = static_cast<int>(vol_history.size());
    if (n == 0) return 0.5;

    double current = vol_history(n - 1);
    if (std::isnan(current)) return 0.5;

    // Count how many values in the lookback window are below current
    int start = std::max(0, n - lookback);
    int below = 0;
    int total = 0;
    for (int i = start; i < n; ++i) {
        if (!std::isnan(vol_history(i))) {
            if (vol_history(i) <= current) ++below;
            ++total;
        }
    }
    return (total > 0) ? static_cast<double>(below) / total : 0.5;
}

std::string CalendarMacroCalculator::classify_trend(double ret_20d, double ret_60d) {
    if (ret_20d > 0 && ret_60d > 0) return "bull";
    if (ret_20d < 0 && ret_60d < 0) return "bear";
    if (ret_20d > 0 && ret_60d < 0) return "reversal_up";
    return "reversal_down";
}

int CalendarMacroCalculator::regime_code(bool is_bull, bool is_high_vol) {
    if (is_bull && !is_high_vol) return 0;
    if (is_bull && is_high_vol) return 1;
    if (!is_bull && !is_high_vol) return 2;
    if (!is_bull && is_high_vol) return 3;
    return 4;
}

std::vector<std::string> CalendarMacroCalculator::feature_names() {
    return {
        "is_spring_festival",      // 0
        "is_national_day",         // 1
        "is_two_sessions",         // 2
        "is_month_end",            // 3
        "day_of_week",             // 4
        "day_of_month_frac",       // 5
        "is_quarter_end",          // 6
        "is_year_start",           // 7
        "market_ret_20d",          // 8
        "market_ret_60d",          // 9
        "trend_bull",              // 10
        "trend_bear",              // 11
        "trend_reversal_up",       // 12
        "trend_reversal_down",     // 13
        "market_vol_20d",          // 14
        "market_vol_60d",          // 15
        "vol_regime_high",         // 16
        "vol_regime_low",          // 17
        "vol_regime_expanding",    // 18
        "regime_code",             // 19
    };
}

// ============================================================================
// Main compute
// ============================================================================

FeatureSet CalendarMacroCalculator::compute(
    const std::vector<BarSeries>& series,
    const std::unordered_map<Symbol, Instrument>& /*instruments*/) const {
    if (series.empty()) return {};

    int n_stocks = static_cast<int>(series.size());

    // Find max length and determine the evaluation date
    int max_len = 0;
    Date eval_date{};
    for (const auto& bs : series) {
        int n = static_cast<int>(bs.size());
        max_len = std::max(max_len, n);
        if (!bs.empty()) {
            eval_date = bs.bars.back().date;
        }
    }
    if (max_len < 20) return {};

    // Compute market-level statistics (same for all stocks on a given date)
    auto mkt_ret = market_return_series(series, max_len);
    auto mkt_vol_20 = market_volatility_series(series, 20, max_len);
    auto mkt_vol_60 = market_volatility_series(series, 60, max_len);

    // Market return over 20d and 60d (cumulative from daily market returns)
    auto mkt_ret_cum_20 = rolling_sum(mkt_ret, 20);
    auto mkt_ret_cum_60 = rolling_sum(mkt_ret, 60);

    // Get latest values
    auto last = [](const Eigen::VectorXd& v) -> double {
        return v.size() > 0 ? v(v.size() - 1) : std::numeric_limits<double>::quiet_NaN();
    };

    double market_ret_20d = last(mkt_ret_cum_20);
    double market_ret_60d = last(mkt_ret_cum_60);
    double market_vol_20d = last(mkt_vol_20);
    double market_vol_60d = last(mkt_vol_60);

    // Calendar flags for the evaluation date
    CalendarFlags cflags = calendar_flags(eval_date);

    // Trend classification
    std::string trend = classify_trend(market_ret_20d, market_ret_60d);
    double trend_bull = (trend == "bull") ? 1.0 : 0.0;
    double trend_bear = (trend == "bear") ? 1.0 : 0.0;
    double trend_rev_up = (trend == "reversal_up") ? 1.0 : 0.0;
    double trend_rev_down = (trend == "reversal_down") ? 1.0 : 0.0;

    // Volatility regime
    double vol_pctl = vol_percentile(mkt_vol_20, 250);
    double vol_high = (vol_pctl > 0.75) ? 1.0 : 0.0;
    double vol_low = (vol_pctl < 0.25) ? 1.0 : 0.0;
    double vol_expanding = (!std::isnan(market_vol_20d) && !std::isnan(market_vol_60d) &&
                            market_vol_20d > market_vol_60d) ? 1.0 : 0.0;

    // Combined regime code
    bool is_bull = (trend == "bull");
    bool is_high_vol = (vol_pctl > 0.75);
    double rc = static_cast<double>(regime_code(is_bull, is_high_vol));

    // All these features are cross-sectionally constant (same for all stocks)
    auto names = feature_names();
    constexpr int n_features = 20;

    Eigen::MatrixXd mat(n_stocks, n_features);

    std::vector<Symbol> symbols;
    std::vector<Date> dates;

    for (int s = 0; s < n_stocks; ++s) {
        symbols.push_back(series[s].symbol);
        dates.push_back(series[s].empty() ? Date{} : series[s].bars.back().date);

        mat(s, 0) = cflags.is_spring_festival;
        mat(s, 1) = cflags.is_national_day;
        mat(s, 2) = cflags.is_two_sessions;
        mat(s, 3) = cflags.is_month_end;
        mat(s, 4) = cflags.day_of_week;
        mat(s, 5) = cflags.day_of_month_frac;
        mat(s, 6) = cflags.is_quarter_end;
        mat(s, 7) = cflags.is_year_start;
        mat(s, 8) = market_ret_20d;
        mat(s, 9) = market_ret_60d;
        mat(s, 10) = trend_bull;
        mat(s, 11) = trend_bear;
        mat(s, 12) = trend_rev_up;
        mat(s, 13) = trend_rev_down;
        mat(s, 14) = market_vol_20d;
        mat(s, 15) = market_vol_60d;
        mat(s, 16) = vol_high;
        mat(s, 17) = vol_low;
        mat(s, 18) = vol_expanding;
        mat(s, 19) = rc;
    }

    FeatureSet fs;
    fs.names = names;
    fs.symbols = std::move(symbols);
    fs.dates = std::move(dates);
    fs.matrix = std::move(mat);
    return fs;
}

} // namespace trade
