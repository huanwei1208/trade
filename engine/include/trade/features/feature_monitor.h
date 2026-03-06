#pragma once

#include "trade/features/feature_engine.h"

#include <Eigen/Dense>
#include <string>
#include <unordered_map>
#include <vector>

namespace trade {

// ============================================================================
// FeatureMonitor -- Factor performance monitoring and retirement
// ============================================================================
//
// Tracks the predictive power of each feature over time and provides
// retirement recommendations when a factor's signal decays.
//
// Metrics tracked per feature:
//
// --- Information Coefficient (IC) ---
//   IC:       Pearson correlation between feature value and forward return
//   RankIC:   Spearman rank correlation (more robust to outliers)
//   IC_IR:    mean(IC) / std(IC) over a rolling window (Sharpe of IC)
//
// --- Decay detection ---
//   A factor is considered "decaying" when its rolling IC series shows a
//   statistically significant downward trend (via linear regression on IC).
//
// --- Retirement rules ---
//   A factor is flagged for retirement when ALL of the following hold:
//     1. In 3 consecutive 60-trading-day windows, |mean_RankIC| < threshold
//        (default threshold = 0.02, i.e., "near-zero" predictive power)
//     2. IC_IR (over 180d) < 0.1
//     3. The net-of-cost return of a long-short portfolio sorted on the
//        factor is negative over the most recent 120d
//     4. The current market regime is NOT the factor's known "best regime"
//        (i.e., the factor only works in an expired regime)
//
//   Retired factors are excluded from the feature matrix but kept in a
//   watch-list for potential reinstatement if conditions change.
//

// Per-feature monitoring state
struct FeatureHealth {
    std::string feature_name;

    // Rolling IC/RankIC series (one value per date)
    Eigen::VectorXd ic_series;
    Eigen::VectorXd rank_ic_series;

    // Summary statistics (updated on each evaluation)
    double mean_ic = 0.0;
    double std_ic = 0.0;
    double mean_rank_ic = 0.0;
    double std_rank_ic = 0.0;
    double ic_ir = 0.0;              // mean(IC) / std(IC)
    double rank_ic_ir = 0.0;         // mean(RankIC) / std(RankIC)

    // Decay detection
    double ic_trend_slope = 0.0;     // slope of linear fit on IC series
    double ic_trend_pvalue = 1.0;    // p-value of the slope being < 0
    bool is_decaying = false;        // trend_slope < 0 and p < 0.05

    // Retirement evaluation
    int consecutive_near_zero_windows = 0;  // count of 60d windows
    double net_of_cost_return_120d = 0.0;   // long-short net return
    bool is_retired = false;
    std::string retirement_reason;
};

class FeatureMonitor {
public:
    struct Config {
        // IC calculation
        int ic_rolling_window = 20;          // days per IC data point
        int ic_summary_window = 180;         // days for IC_IR calculation

        // Decay detection
        int decay_lookback = 120;            // days for trend regression
        double decay_pvalue_threshold = 0.05;

        // Retirement thresholds
        double near_zero_ic_threshold = 0.02;
        int near_zero_window_size = 60;       // trading days per window
        int near_zero_consecutive_req = 3;    // 3 consecutive windows
        double min_ic_ir = 0.1;
        double min_net_return = 0.0;          // net-of-cost return threshold

        // Forward return horizon for IC calculation (in trading days)
        int forward_return_days = 5;

        // Transaction cost for net-of-cost return estimation
        double one_way_cost = 0.0015;         // 15 bps per side
    };

    FeatureMonitor();
    explicit FeatureMonitor(Config cfg);

    // --- Core API --------------------------------------------------------

    // Update monitoring state with new data.
    // |features|:       (N_stocks, K_features) matrix for the current date.
    // |forward_returns|: (N_stocks,) vector of forward returns.
    // |feature_names|:   names corresponding to columns of |features|.
    void update(
        const Eigen::MatrixXd& features,
        const Eigen::VectorXd& forward_returns,
        const std::vector<std::string>& feature_names,
        Date eval_date);

    // Evaluate all features and determine retirement status.
    // |current_regime|: used for regime-conditional retirement rule.
    void evaluate(Regime current_regime);

    // Get the health status of a specific feature.
    const FeatureHealth& health(const std::string& name) const;

    // Get all features currently marked for retirement.
    std::vector<std::string> retired_features() const;

    // Get all active (non-retired) features.
    std::vector<std::string> active_features() const;

    // Reinstate a previously retired feature (manual override or
    // automatic if conditions improve).
    void reinstate(const std::string& name);

    // Get a summary report of all feature health states.
    std::vector<FeatureHealth> report() const;

    // --- Static computation helpers --------------------------------------

    // Pearson correlation between two vectors (ignoring NaN pairs).
    static double pearson_ic(
        const Eigen::VectorXd& feature,
        const Eigen::VectorXd& forward_return);

    // Spearman rank correlation (rank-based IC).
    static double spearman_rank_ic(
        const Eigen::VectorXd& feature,
        const Eigen::VectorXd& forward_return);

    // IC_IR = mean(ic_series) / std(ic_series)
    static double compute_ic_ir(const Eigen::VectorXd& ic_series);

    // Linear regression of IC series on time index.
    // Returns (slope, p_value).
    static std::pair<double, double> ic_trend_test(
        const Eigen::VectorXd& ic_series);

    // Estimate net-of-cost long-short return for a factor.
    // Constructs equal-weighted top/bottom quintile portfolios.
    // |feature|:        (N,) feature values at portfolio formation.
    // |forward_return|: (N,) realised returns over holding period.
    // |one_way_cost|:   transaction cost per trade side.
    static double long_short_net_return(
        const Eigen::VectorXd& feature,
        const Eigen::VectorXd& forward_return,
        double one_way_cost);

    // Check near-zero IC condition for a window.
    static bool is_near_zero_window(
        const Eigen::VectorXd& rank_ic_series,
        int window_start, int window_size,
        double threshold);

    const Config& config() const { return config_; }

private:
    Config config_;
    std::unordered_map<std::string, FeatureHealth> health_map_;
    std::vector<Date> eval_dates_;

    // Per-feature regime mapping: which regime is the factor's "best"?
    // Factors are only retired when not in their best regime.
    std::unordered_map<std::string, Regime> best_regime_;

    // Update summary statistics for a single feature
    void update_summary(FeatureHealth& fh, int summary_window) const;

    // Check retirement conditions for a single feature
    bool check_retirement(const FeatureHealth& fh, Regime regime) const;
};

} // namespace trade
