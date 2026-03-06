#pragma once

#include "trade/common/types.h"
#include "trade/model/instrument.h"

#include <Eigen/Dense>
#include <string>
#include <unordered_map>
#include <vector>

namespace trade {

// ============================================================================
// PositionSizer: constraint-aware position sizing
// ============================================================================
// Takes raw alpha-implied weights and applies a full set of risk constraints
// to produce tradeable portfolio weights.  Constraints are applied iteratively
// via clamp-and-rescale until all hard limits are satisfied (or max iterations
// is reached).
//
// Constraint catalogue:
//   1. Single-stock weight:       soft 8%, hard 10%
//   2. Single-stock liquidity:    <= 15% x 20d ADV
//   3. Single-industry weight:    soft 30%, hard 35%
//   4. Top-3 combined weight:     <= 22%
//   5. Style factor exposure:     |z-score| <= 1.0 per factor
//   6. Portfolio Beta:            [0.6, 1.2]
//   7. Liquidation days:          <= 2.5 days
//   8. Volatility-bucket caps:    low-vol 8-10%, mid-vol 6-8%, high-vol 3-5%
//
class PositionSizer {
public:
    // -----------------------------------------------------------------------
    // Constraint parameters
    // -----------------------------------------------------------------------
    struct Constraints {
        // Single stock
        double single_stock_soft_pct = 0.08;
        double single_stock_hard_pct = 0.10;

        // Liquidity: position <= fraction * 20d_adv
        double liquidity_adv_fraction = 0.15;

        // Industry concentration
        double industry_soft_pct = 0.30;
        double industry_hard_pct = 0.35;

        // Top-N combined
        int top_n = 3;
        double top_n_combined_pct = 0.22;

        // Style factor z-score bounds
        double factor_exposure_abs_max = 1.0;

        // Portfolio Beta
        double beta_min = 0.6;
        double beta_max = 1.2;

        // Liquidation horizon
        double max_liquidation_days = 2.5;

        // Volatility-bucket caps (per-stock max weight by vol regime)
        double low_vol_cap_min = 0.08;
        double low_vol_cap_max = 0.10;
        double mid_vol_cap_min = 0.06;
        double mid_vol_cap_max = 0.08;
        double high_vol_cap_min = 0.03;
        double high_vol_cap_max = 0.05;

        // Vol thresholds to classify stocks
        double low_vol_threshold = 0.20;   // annualised vol < 20%
        double high_vol_threshold = 0.40;  // annualised vol > 40%

        // Iteration control
        int max_iterations = 50;
        double convergence_tol = 1e-6;
    };

    // -----------------------------------------------------------------------
    // Per-stock risk information (input)
    // -----------------------------------------------------------------------
    struct StockRisk {
        Symbol symbol;
        SWIndustry industry = SWIndustry::kUnknown;
        double annualised_vol = 0.0;    // individual stock annualised vol
        double beta = 1.0;             // beta to benchmark
        double adv_20d = 0.0;          // 20-day average daily volume (notional)
        double position_notional = 0.0; // current position size in notional
    };

    // -----------------------------------------------------------------------
    // Sizing result
    // -----------------------------------------------------------------------
    struct SizingResult {
        Eigen::VectorXd weights;                // final constrained weights (N,)
        std::vector<Symbol> symbols;            // corresponding symbols

        // Diagnostics
        double portfolio_beta = 0.0;
        double liquidation_days = 0.0;
        double gross_exposure = 0.0;
        double max_single_stock = 0.0;
        double max_industry_weight = 0.0;
        double top_n_combined = 0.0;
        int iterations_used = 0;
        bool converged = false;

        // Per-constraint violation flags (before resolution)
        struct Violations {
            int single_stock = 0;
            int liquidity = 0;
            int industry = 0;
            int top_n = 0;
            int factor_exposure = 0;
            int beta = 0;
            int liquidation = 0;
            int vol_bucket = 0;
        } violations;
    };

    PositionSizer() : constraints_{} {}
    explicit PositionSizer(Constraints constraints)
        : constraints_(constraints) {}

    // -----------------------------------------------------------------------
    // Main sizing interface
    // -----------------------------------------------------------------------
    //   alphas:           (N,) raw alpha scores / desired weights
    //   risks:            per-stock risk information
    //   factor_loadings:  (N x K) factor loading matrix (optional)
    //   cov:              (N x N) covariance matrix (optional, for beta/liq)
    SizingResult size_positions(
        const Eigen::VectorXd& alphas,
        const std::vector<StockRisk>& risks,
        const Eigen::MatrixXd& factor_loadings = {},
        const Eigen::MatrixXd& cov = {}) const;

    // -----------------------------------------------------------------------
    // Individual constraint checks (can be used standalone)
    // -----------------------------------------------------------------------

    // Clamp single-stock weights to hard limit
    static Eigen::VectorXd clamp_single_stock(
        const Eigen::VectorXd& weights, double hard_pct);

    // Clamp industry exposures
    static Eigen::VectorXd clamp_industry(
        const Eigen::VectorXd& weights,
        const std::vector<SWIndustry>& industries,
        double hard_pct);

    // Clamp top-N combined weight
    static Eigen::VectorXd clamp_top_n(
        const Eigen::VectorXd& weights, int n, double max_combined);

    // Adjust weights to satisfy Beta bounds
    static Eigen::VectorXd adjust_beta(
        const Eigen::VectorXd& weights,
        const Eigen::VectorXd& betas,
        double beta_min, double beta_max);

    // Compute liquidation days: max_i(|w_i * NAV| / adv_i)
    static double compute_liquidation_days(
        const Eigen::VectorXd& weights,
        const Eigen::VectorXd& adv,
        double nav);

    // Volatility bucket cap: per-stock weight cap based on vol regime
    double vol_bucket_cap(double annualised_vol) const;

    const Constraints& constraints() const { return constraints_; }
    void set_constraints(const Constraints& c) { constraints_ = c; }

private:
    Constraints constraints_;
};

} // namespace trade
