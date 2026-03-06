#pragma once

#include "trade/common/types.h"
#include "trade/model/bar.h"
#include "trade/model/market.h"
#include <Eigen/Dense>
#include <vector>
#include <unordered_map>
#include <string>

namespace trade {

// ---------------------------------------------------------------------------
// Market overview statistics for a single date
// ---------------------------------------------------------------------------
struct MarketOverview {
    Date date;
    int total_stocks = 0;
    int up_count = 0;              // stocks with positive returns
    int down_count = 0;            // stocks with negative returns
    int flat_count = 0;            // stocks with zero return
    double up_ratio = 0.0;         // up_count / total_stocks
    double total_amount = 0.0;     // aggregate turnover in yuan
    double median_turnover = 0.0;  // median turnover rate across stocks
    double mean_return = 0.0;      // equal-weighted mean return
};

// ---------------------------------------------------------------------------
// Money-making effect: gauges breadth of participation in rallies
// ---------------------------------------------------------------------------
struct MoneyMakingEffect {
    Date date;
    double below_20dma_ratio = 0.0;    // fraction of stocks trading below 20-day MA
    int limit_up_count = 0;            // stocks hitting upper price limit
    int limit_down_count = 0;          // stocks hitting lower price limit
    int limit_up_broken_count = 0;     // stocks that hit limit-up but failed to hold
    double median_return = 0.0;        // median stock return (proxy for typical investor)
    double pct75_return = 0.0;         // 75th percentile return
    double pct25_return = 0.0;         // 25th percentile return
};

// ---------------------------------------------------------------------------
// Style exposure comparison (large/small cap, growth/value)
// ---------------------------------------------------------------------------
struct StyleExposure {
    Date date;
    double large_cap_return = 0.0;     // top-decile market-cap weighted return
    double small_cap_return = 0.0;     // bottom-decile market-cap weighted return
    double large_small_spread = 0.0;   // large - small
    double growth_return = 0.0;        // growth basket return
    double value_return = 0.0;         // value basket return
    double growth_value_spread = 0.0;  // growth - value
};

// ---------------------------------------------------------------------------
// Per-stock distributional statistics over a lookback window
// ---------------------------------------------------------------------------
struct StockDistributionStats {
    int n = 0;                         // number of observations
    double mean_return = 0.0;
    double std_return = 0.0;           // annualisable daily std
    double skewness = 0.0;
    double kurtosis = 0.0;            // excess kurtosis
    double min_return = 0.0;
    double max_return = 0.0;
    double pct5_return = 0.0;         // 5th percentile
    double pct95_return = 0.0;        // 95th percentile
};

// ---------------------------------------------------------------------------
// DescriptiveStats: collection of static methods for market-wide analytics
// ---------------------------------------------------------------------------
class DescriptiveStats {
public:
    // ----- Market overview ------------------------------------------------

    /// Compute market overview from a cross-sectional snapshot.
    static MarketOverview market_overview(const MarketSnapshot& snapshot);

    /// Compute market overview from raw bar data for a single date.
    static MarketOverview market_overview(const std::vector<Bar>& bars, Date date);

    // ----- Money-making effect --------------------------------------------

    /// Evaluate money-making effect.
    /// @param snapshot   Cross-sectional snapshot for the date.
    /// @param ma20_map   Map from Symbol to its 20-day moving average price.
    static MoneyMakingEffect money_making_effect(
        const MarketSnapshot& snapshot,
        const std::unordered_map<Symbol, double>& ma20_map);

    // ----- Style exposure -------------------------------------------------

    /// Compare large/small cap and growth/value performance.
    /// @param snapshot       Cross-sectional snapshot.
    /// @param market_caps    Map from Symbol to market capitalisation (yuan).
    /// @param growth_scores  Map from Symbol to growth score (higher = more growth).
    static StyleExposure style_exposure(
        const MarketSnapshot& snapshot,
        const std::unordered_map<Symbol, double>& market_caps,
        const std::unordered_map<Symbol, double>& growth_scores);

    // ----- Individual stock statistics ------------------------------------

    /// Compute return distribution statistics for a single symbol.
    /// @param returns  Vector of daily log or simple returns.
    static StockDistributionStats return_distribution(
        const Eigen::VectorXd& returns);

    /// Compute annualised volatility from daily returns.
    /// @param returns  Daily return series.
    /// @param trading_days_per_year  Default 242 for A-shares.
    static double annualised_volatility(
        const Eigen::VectorXd& returns,
        int trading_days_per_year = 242);

    /// Compute cross-sectional correlation matrix for multiple symbols.
    /// @param return_matrix  N x T matrix where row i = returns of symbol i.
    /// @return N x N Pearson correlation matrix.
    static Eigen::MatrixXd correlation_matrix(
        const Eigen::MatrixXd& return_matrix);

    /// Rank-based (Spearman) cross-sectional correlation matrix.
    static Eigen::MatrixXd rank_correlation_matrix(
        const Eigen::MatrixXd& return_matrix);

    // ----- Helpers --------------------------------------------------------

    /// Compute quantile of a sorted or unsorted vector.
    /// @param data  Input values (will not be modified).
    /// @param q     Quantile in [0, 1].
    static double quantile(const Eigen::VectorXd& data, double q);

    /// Compute skewness of a sample.
    static double skewness(const Eigen::VectorXd& data);

    /// Compute excess kurtosis of a sample.
    static double kurtosis(const Eigen::VectorXd& data);

    /// Convert a vector of Bar returns to an Eigen::VectorXd.
    static Eigen::VectorXd bars_to_returns(const std::vector<Bar>& bars);
};

} // namespace trade
