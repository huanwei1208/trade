#pragma once

#include "trade/common/types.h"
#include <Eigen/Dense>
#include <vector>
#include <string>

namespace trade {

// ---------------------------------------------------------------------------
// Result of IC analysis at a single forward horizon
// ---------------------------------------------------------------------------
struct ICResult {
    int horizon = 0;               // forward-return horizon in trading days
    double ic = 0.0;               // Pearson IC (cross-sectional)
    double rank_ic = 0.0;          // Spearman Rank IC
    double ic_std = 0.0;           // standard deviation of IC over time
    double ic_ir = 0.0;            // IC_IR = mean(IC) / std(IC)
    double rank_ic_ir = 0.0;       // Rank IC IR
    double ic_pvalue = 0.0;        // two-sided t-test p-value for IC != 0
    int n_periods = 0;             // number of cross-sectional periods used
};

// ---------------------------------------------------------------------------
// IC decay profile: IC measured at multiple forward horizons
// ---------------------------------------------------------------------------
struct ICDecayProfile {
    std::string factor_name;
    std::vector<ICResult> results;  // one per horizon (e.g., 1d, 2d, 5d, 10d, 20d)

    /// The horizon at which |IC| is maximised.
    int peak_horizon() const;

    /// Half-life: first horizon where |IC| < 0.5 * peak |IC|.
    int half_life() const;
};

// ---------------------------------------------------------------------------
// CorrelationAnalysis: static methods for factor-return correlation analytics
// ---------------------------------------------------------------------------
class CorrelationAnalysis {
public:
    // ----- Single-period IC ------------------------------------------------

    /// Compute cross-sectional Pearson Information Coefficient.
    /// @param factor_values  N-vector of factor exposures (one per stock).
    /// @param forward_returns  N-vector of corresponding forward returns.
    /// @return Pearson correlation (IC).
    static double information_coefficient(
        const Eigen::VectorXd& factor_values,
        const Eigen::VectorXd& forward_returns);

    /// Compute cross-sectional Spearman Rank IC.
    static double rank_ic(
        const Eigen::VectorXd& factor_values,
        const Eigen::VectorXd& forward_returns);

    // ----- Time-series IC summary ------------------------------------------

    /// Compute IC summary statistics over multiple cross-sections.
    /// @param factor_panel  N x T matrix (N stocks, T dates); each column is
    ///                      the cross-sectional factor exposure at date t.
    /// @param return_panel  N x T matrix of forward returns aligned with factor_panel.
    /// @param horizon       Forward return horizon in trading days (for labelling).
    /// @return ICResult aggregated across all T cross-sections.
    static ICResult ic_summary(
        const Eigen::MatrixXd& factor_panel,
        const Eigen::MatrixXd& return_panel,
        int horizon);

    /// Compute IC_IR = mean(IC_series) / std(IC_series).
    /// @param ic_series  Time series of cross-sectional ICs.
    static double ic_ir(const Eigen::VectorXd& ic_series);

    // ----- IC decay --------------------------------------------------------

    /// Compute IC decay profile across multiple forward horizons.
    /// @param factor_panel   N x T factor exposure matrix.
    /// @param price_panel    N x T price matrix (used to compute forward returns
    ///                       at each requested horizon).
    /// @param horizons       List of forward horizons (e.g., {1, 2, 5, 10, 20}).
    /// @param factor_name    Name of the factor (for labelling).
    /// @return ICDecayProfile containing one ICResult per horizon.
    static ICDecayProfile ic_decay(
        const Eigen::MatrixXd& factor_panel,
        const Eigen::MatrixXd& price_panel,
        const std::vector<int>& horizons,
        const std::string& factor_name = "");

    // ----- Cross-factor correlation ----------------------------------------

    /// Cross-sectional correlation matrix between multiple factors at a date.
    /// @param factor_matrix  N x K matrix (N stocks, K factors).
    /// @return K x K Pearson correlation matrix.
    static Eigen::MatrixXd cross_factor_correlation(
        const Eigen::MatrixXd& factor_matrix);

    /// Rank-based cross-factor correlation matrix.
    static Eigen::MatrixXd cross_factor_rank_correlation(
        const Eigen::MatrixXd& factor_matrix);

    // ----- Utilities -------------------------------------------------------

    /// Convert raw values to fractional ranks in [0, 1].
    /// Ties receive the average rank.
    static Eigen::VectorXd to_ranks(const Eigen::VectorXd& values);

    /// Compute forward returns from a price vector at a given horizon.
    /// @param prices   T-vector of prices ordered by date.
    /// @param horizon  Number of trading days forward.
    /// @return (T - horizon)-vector of forward returns.
    static Eigen::VectorXd forward_returns(
        const Eigen::VectorXd& prices,
        int horizon);

    /// Two-sided t-test p-value for a sample mean.
    static double ttest_pvalue(const Eigen::VectorXd& sample);
};

} // namespace trade
