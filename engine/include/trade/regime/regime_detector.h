#pragma once

#include "trade/common/types.h"

#include <Eigen/Dense>
#include <string>
#include <vector>

namespace trade {

// ============================================================================
// RegimeDetector: market regime and volatility regime detection
// ============================================================================
//
// Market regime classification:
//   Bull:   index > 120-DMA AND up_count > 60% AND annualised vol < 22%
//   Bear:   index < 120-DMA AND up_count < 45% AND trend slope negative
//   Shock:  annualised vol > 35%  OR  single-day |index return| > 3%
//
// Volatility regime classification (orthogonal to market regime):
//   Low:    realised vol in bottom tercile of 2-year distribution
//   High:   realised vol in top tercile of 2-year distribution
//   Normal: in between
//
// Both regimes are refreshed daily.  Shock overrides Bull/Bear when triggered.
//
class RegimeDetector {
public:
    // -----------------------------------------------------------------------
    // Volatility regime (orthogonal to market regime)
    // -----------------------------------------------------------------------
    enum class VolRegime : uint8_t {
        kLow = 0,
        kNormal = 1,
        kHigh = 2,
    };

    // -----------------------------------------------------------------------
    // Market breadth input
    // -----------------------------------------------------------------------
    struct MarketBreadth {
        int total_stocks = 0;
        int up_stocks = 0;                  // stocks with positive returns today
        int limit_up = 0;
        int limit_down = 0;

        double up_ratio() const {
            return total_stocks > 0
                ? static_cast<double>(up_stocks) / total_stocks
                : 0.0;
        }
    };

    // -----------------------------------------------------------------------
    // Detection result
    // -----------------------------------------------------------------------
    struct RegimeResult {
        Regime market_regime = Regime::kShock;
        VolRegime vol_regime = VolRegime::kNormal;

        // Underlying indicators
        double index_price = 0.0;
        double dma_120 = 0.0;              // 120-day moving average of index
        double index_above_dma_pct = 0.0;  // index / dma_120 - 1
        double up_ratio = 0.0;             // fraction of stocks up
        double annualised_vol = 0.0;       // realised vol (20d, annualised)
        double single_day_return = 0.0;    // most recent day return

        // Vol regime quantile info
        double vol_quantile = 0.0;         // percentile in 2-year distribution
        double vol_tercile_low = 0.0;      // 33rd percentile threshold
        double vol_tercile_high = 0.0;     // 67th percentile threshold

        // Trend indicator
        double trend_slope = 0.0;          // linear regression slope (60d)
        bool trend_down = false;

        // Shock trigger flags
        bool shock_vol_trigger = false;    // vol > 35%
        bool shock_day_trigger = false;    // |single day| > 3%

        // Human-readable
        std::string regime_name() const {
            switch (market_regime) {
                case Regime::kBull: return "Bull";
                case Regime::kBear: return "Bear";
                case Regime::kShock: return "Shock";
            }
            return "Unknown";
        }

        std::string vol_regime_name() const {
            switch (vol_regime) {
                case VolRegime::kLow: return "LowVol";
                case VolRegime::kNormal: return "NormalVol";
                case VolRegime::kHigh: return "HighVol";
            }
            return "Unknown";
        }
    };

    // -----------------------------------------------------------------------
    // Configuration
    // -----------------------------------------------------------------------
    struct Config {
        // DMA lookback
        int dma_period = 120;

        // Bull thresholds
        double bull_up_ratio_min = 0.60;
        double bull_vol_max = 0.22;        // annualised

        // Bear thresholds
        double bear_up_ratio_max = 0.45;

        // Shock thresholds
        double shock_vol_threshold = 0.35; // annualised
        double shock_day_return_threshold = 0.03; // |return| > 3%

        // Volatility regime
        int vol_history_days = 504;        // ~2 years of trading days
        int realized_vol_window = 20;      // 20-day realised vol

        // Trend
        int trend_window = 60;             // 60-day trend slope

        // Regime persistence: require N consecutive days before switching
        int min_persistence_days = 3;
    };

    RegimeDetector() : config_{} {}
    explicit RegimeDetector(Config cfg) : config_(cfg) {}

    // -----------------------------------------------------------------------
    // Core interface
    // -----------------------------------------------------------------------

    // Detect the current market regime and volatility regime.
    //   index_prices:  daily index close prices (oldest first, at least 120 days)
    //   market_breadth: today's market breadth snapshot
    RegimeResult detect(
        const std::vector<double>& index_prices,
        const MarketBreadth& market_breadth) const;

    // Detect only the volatility regime from a history of realised vol.
    //   vol_history: daily realised vol values (at least vol_history_days)
    VolRegime detect_vol_regime(const std::vector<double>& vol_history) const;

    // -----------------------------------------------------------------------
    // Indicator calculations (usable standalone)
    // -----------------------------------------------------------------------

    // Simple moving average of the last N prices
    static double sma(const std::vector<double>& prices, int period);

    // Realised volatility (annualised) from daily close prices
    static double realized_vol(const std::vector<double>& prices, int window);

    // Linear regression slope over a window (normalised by mean price)
    static double trend_slope(const std::vector<double>& prices, int window);

    // Compute quantile of a value within a distribution
    static double quantile_rank(double value, const std::vector<double>& distribution);

    // -----------------------------------------------------------------------
    // Regime history tracking
    // -----------------------------------------------------------------------

    // Update with a new day's data and return the regime.
    // Maintains internal state for persistence filtering.
    RegimeResult update(
        const std::vector<double>& index_prices,
        const MarketBreadth& market_breadth);

    // Get the current confirmed regime (after persistence filter)
    Regime current_regime() const { return confirmed_regime_; }
    VolRegime current_vol_regime() const { return confirmed_vol_regime_; }

    // Number of consecutive days in the current regime
    int regime_duration() const { return regime_duration_; }

    const Config& config() const { return config_; }

private:
    Config config_;

    // State for persistence filter
    Regime confirmed_regime_ = Regime::kShock;
    Regime pending_regime_ = Regime::kShock;
    VolRegime confirmed_vol_regime_ = VolRegime::kNormal;
    int pending_count_ = 0;
    int regime_duration_ = 0;
};

} // namespace trade
