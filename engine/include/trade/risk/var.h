#pragma once

#include "trade/common/types.h"

#include <Eigen/Dense>
#include <cmath>
#include <optional>
#include <string>
#include <vector>

namespace trade {

// ============================================================================
// VaRCalculator: Three-layer VaR / CVaR system
// ============================================================================
// Layer 1 -- Parametric VaR/CVaR
//   sigma_p^2 = w' * Sigma * w  (portfolio variance under normal assumption)
//   VaR_alpha  = mu_p + z_alpha * sigma_p
//   CVaR_alpha = mu_p + phi(z_alpha) / (1-alpha) * sigma_p
//
// Layer 2 -- Historical simulation VaR/CVaR
//   Full re-pricing using historical return scenarios; captures non-normal tails.
//
// Layer 3 -- Monte Carlo stress VaR
//   Simulated returns with fat tails (Student-t, df=5) and liquidity constraints
//   (position-level haircut on illiquid names).
//
// Production metric:
//   VaR_1d_99 = max(L1, L2, L3)
//
class VaRCalculator {
public:
    struct Config {
        double confidence_level = 0.99;     // 99% VaR
        int historical_window = 500;        // trading days for L2
        int mc_simulations = 10000;         // Monte Carlo paths for L3
        double mc_t_df = 5.0;              // Student-t degrees of freedom
        int horizon_days = 1;              // VaR horizon (1-day default)
        unsigned int random_seed = 42;     // for reproducibility
    };

    VaRCalculator() : config_{} {}
    explicit VaRCalculator(Config cfg) : config_(cfg) {}

    // -----------------------------------------------------------------------
    // Single-layer results
    // -----------------------------------------------------------------------
    struct VaRResult {
        double var = 0.0;                   // Value-at-Risk (positive = loss)
        double cvar = 0.0;                  // Conditional VaR (expected shortfall)
        double confidence = 0.0;            // confidence level used
        std::string method;                 // "parametric", "historical", "montecarlo"
    };

    // -----------------------------------------------------------------------
    // Combined result from all three layers
    // -----------------------------------------------------------------------
    struct CombinedVaR {
        VaRResult parametric;               // L1
        VaRResult historical;               // L2
        VaRResult monte_carlo;              // L3
        double var_1d_99 = 0.0;             // max(L1, L2, L3) VaR
        double cvar_1d_99 = 0.0;            // max(L1, L2, L3) CVaR
    };

    // -----------------------------------------------------------------------
    // Layer 1: Parametric VaR / CVaR
    // -----------------------------------------------------------------------
    //   weights: (N,) portfolio weights
    //   cov:     (N x N) covariance matrix
    //   mu:      (N,) expected returns (optional, defaults to zero)
    VaRResult parametric_var(
        const Eigen::VectorXd& weights,
        const Eigen::MatrixXd& cov,
        const Eigen::VectorXd& mu = {}) const;

    // -----------------------------------------------------------------------
    // Layer 2: Historical simulation VaR / CVaR
    // -----------------------------------------------------------------------
    //   weights:         (N,) portfolio weights
    //   returns_matrix:  (T x N) historical returns
    VaRResult historical_var(
        const Eigen::VectorXd& weights,
        const Eigen::MatrixXd& returns_matrix) const;

    // -----------------------------------------------------------------------
    // Layer 3: Monte Carlo stress VaR
    // -----------------------------------------------------------------------
    //   weights:   (N,) portfolio weights
    //   cov:       (N x N) covariance matrix
    //   mu:        (N,) expected returns
    //   adv:       (N,) 20-day average daily volume in notional
    //   positions: (N,) position notional values -- for liquidity haircut
    VaRResult monte_carlo_var(
        const Eigen::VectorXd& weights,
        const Eigen::MatrixXd& cov,
        const Eigen::VectorXd& mu,
        const Eigen::VectorXd& adv = {},
        const Eigen::VectorXd& positions = {}) const;

    // -----------------------------------------------------------------------
    // Combined: production metric
    // -----------------------------------------------------------------------
    CombinedVaR compute(
        const Eigen::VectorXd& weights,
        const Eigen::MatrixXd& cov,
        const Eigen::MatrixXd& returns_matrix,
        const Eigen::VectorXd& mu = {},
        const Eigen::VectorXd& adv = {},
        const Eigen::VectorXd& positions = {}) const;

    // -----------------------------------------------------------------------
    // Marginal / Component VaR
    // -----------------------------------------------------------------------

    // Marginal VaR: dVaR / dw_i  (sensitivity of portfolio VaR to weight i)
    Eigen::VectorXd marginal_var(
        const Eigen::VectorXd& weights,
        const Eigen::MatrixXd& cov) const;

    // Component VaR: w_i * marginal_VaR_i  (sums to portfolio VaR)
    Eigen::VectorXd component_var(
        const Eigen::VectorXd& weights,
        const Eigen::MatrixXd& cov) const;

    const Config& config() const { return config_; }

private:
    Config config_;

    // z-score for the given confidence level (e.g. 2.326 for 99%)
    double z_alpha() const;

    // Standard normal PDF
    static double norm_pdf(double x);

    // Standard normal CDF inverse (quantile function)
    static double norm_quantile(double p);
};

} // namespace trade
