#pragma once

#include "trade/features/feature_engine.h"
#include "trade/common/time_utils.h"
#include "trade/model/bar.h"
#include "trade/model/instrument.h"

#include <Eigen/Dense>
#include <string>
#include <unordered_map>
#include <vector>

namespace trade {

// ============================================================================
// CalendarMacroCalculator  (Priority P8 -- Calendar / Macro Features)
// ============================================================================
//
// Calendar-based and macro-regime features that capture seasonality and
// broad market state.  These features are the same for all stocks on a
// given date (cross-sectionally constant), so they are primarily useful
// as conditioning variables or interaction terms.
//
// Features computed:
//
// --- Holiday windows (binary indicators) ---
//   is_spring_festival      1 during spring festival window (pre-3d / post-5d)
//   is_national_day         1 during national day window
//   is_two_sessions         1 during two-sessions window (March political)
//
// --- Calendar position ---
//   is_month_end            1 for last 3 trading days of month
//   day_of_week             day-of-week encoded as [0, 1] (Mon=0.0, Fri=1.0)
//   day_of_month_frac       day / total_trading_days_in_month, in [0, 1]
//   is_quarter_end          1 for last 5 trading days of quarter
//   is_year_start           1 for first 5 trading days of year (January effect)
//
// --- Market trend state ---
//   market_ret_20d          equal-weighted market return over 20 days
//   market_ret_60d          equal-weighted market return over 60 days
//   trend_bull              1 if market_ret_20d > 0 and market_ret_60d > 0
//   trend_bear              1 if market_ret_20d < 0 and market_ret_60d < 0
//   trend_reversal_up       1 if market_ret_20d > 0 and market_ret_60d < 0
//   trend_reversal_down     1 if market_ret_20d < 0 and market_ret_60d > 0
//
// --- Volatility regime ---
//   market_vol_20d          cross-sectional mean of realized_vol_20d
//   market_vol_60d          cross-sectional mean of realized_vol_60d
//   vol_regime_high         1 if market_vol_20d > 75th percentile of 1yr hist
//   vol_regime_low          1 if market_vol_20d < 25th percentile of 1yr hist
//   vol_regime_expanding    1 if market_vol_20d > market_vol_60d (vol rising)
//
// --- Combined regime label ---
//   regime_code             encoded regime: 0=bull+low_vol, 1=bull+high_vol,
//                           2=bear+low_vol, 3=bear+high_vol, 4=shock
//
class CalendarMacroCalculator : public FeatureCalculator {
public:
    std::string group_name() const override { return "calendar_macro"; }

    FeatureSet compute(
        const std::vector<BarSeries>& series,
        const std::unordered_map<Symbol, Instrument>& instruments) const override;

    // --- Individual factor helpers (static for unit-testing) ---------------

    // Calendar indicators for a single date
    struct CalendarFlags {
        double is_spring_festival = 0.0;
        double is_national_day = 0.0;
        double is_two_sessions = 0.0;
        double is_month_end = 0.0;
        double day_of_week = 0.0;       // normalized [0,1]
        double day_of_month_frac = 0.0;
        double is_quarter_end = 0.0;
        double is_year_start = 0.0;
    };

    static CalendarFlags calendar_flags(Date d);

    // Compute equal-weighted market return from all series at each date.
    // Returns: (T,) vector aligned with the date grid.
    static Eigen::VectorXd market_return_series(
        const std::vector<BarSeries>& series, int max_len);

    // Compute cross-sectional mean realized volatility at each date.
    static Eigen::VectorXd market_volatility_series(
        const std::vector<BarSeries>& series, int vol_window, int max_len);

    // Classify trend state from 20d and 60d market returns.
    // Returns one of: "bull", "bear", "reversal_up", "reversal_down"
    static std::string classify_trend(double ret_20d, double ret_60d);

    // Determine volatility regime percentile from historical distribution.
    // |vol_history|: rolling market vol series.
    // |lookback|: number of days to use for percentile (default 250).
    // Returns: percentile of current vol within lookback window, in [0, 1].
    static double vol_percentile(
        const Eigen::VectorXd& vol_history, int lookback = 250);

    // Encode combined regime as integer code.
    static int regime_code(bool is_bull, bool is_high_vol);

    // Feature names for all calendar/macro features
    static std::vector<std::string> feature_names();

private:
    // Check if date is near quarter-end (last 5 trading days)
    static bool is_quarter_end(Date d);

    // Check if date is near year-start (first 5 trading days)
    static bool is_year_start(Date d);
};

} // namespace trade
