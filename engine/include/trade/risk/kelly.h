#pragma once

#include "trade/common/types.h"

#include <Eigen/Dense>
#include <algorithm>
#include <cmath>
#include <vector>

namespace trade {

// ============================================================================
// KellyCalculator: Kelly criterion with risk budgeting and risk parity
// ============================================================================
//
// Three-step position sizing pipeline:
//
// 1. Quarter-Kelly fraction per asset:
//      f_i = 0.25 * mu_i / sigma_i^2
//    where mu_i = expected excess return, sigma_i = individual asset vol.
//
// 2. Risk budget allocation:
//      rb_i  proportional to  clamp(f_i, 0, f_max) * confidence_i
//    Normalised so that sum(rb_i) = 1.  confidence_i in [0, 1] is the
//    model's conviction score for asset i.
//
// 3. Risk-parity adjustment:
//      w_i  proportional to  rb_i / sigma_i
//    Ensures each asset contributes roughly equal risk per unit of budget.
//    Final weights are normalised to sum to the target gross exposure.
//
class KellyCalculator {
public:
    struct Config {
        double kelly_fraction = 0.25;       // quarter Kelly
        double f_max = 0.10;                // max Kelly fraction per asset
        double target_gross_exposure = 1.0; // sum(|w_i|) target
        double min_confidence = 0.0;        // drop assets below this threshold
    };

    KellyCalculator() : config_{} {}
    explicit KellyCalculator(Config cfg) : config_(cfg) {}

    // -----------------------------------------------------------------------
    // Step 1: Raw Kelly fractions
    // -----------------------------------------------------------------------
    //   mu:    (N,) expected excess returns
    //   sigma: (N,) individual asset volatilities
    // Returns: (N,) quarter-Kelly fractions (can be negative for short signals)
    Eigen::VectorXd kelly_fraction(
        const Eigen::VectorXd& mu,
        const Eigen::VectorXd& sigma) const;

    // -----------------------------------------------------------------------
    // Step 2: Risk budget
    // -----------------------------------------------------------------------
    //   kelly:      (N,) raw Kelly fractions from step 1
    //   confidence: (N,) model confidence scores in [0, 1]
    // Returns: (N,) risk budget weights summing to 1 (zero for negative/low f)
    Eigen::VectorXd risk_budget(
        const Eigen::VectorXd& kelly,
        const Eigen::VectorXd& confidence) const;

    // -----------------------------------------------------------------------
    // Step 3: Risk-parity adjusted weights
    // -----------------------------------------------------------------------
    //   risk_budget: (N,) risk budget from step 2
    //   sigma:       (N,) individual asset volatilities
    // Returns: (N,) portfolio weights summing to target_gross_exposure
    Eigen::VectorXd risk_parity_weights(
        const Eigen::VectorXd& risk_budget,
        const Eigen::VectorXd& sigma) const;

    // -----------------------------------------------------------------------
    // Convenience: full pipeline in one call
    // -----------------------------------------------------------------------
    //   mu:         (N,) expected excess returns
    //   sigma:      (N,) individual asset volatilities
    //   confidence: (N,) model confidence scores
    // Returns: (N,) final portfolio weights
    Eigen::VectorXd compute_weights(
        const Eigen::VectorXd& mu,
        const Eigen::VectorXd& sigma,
        const Eigen::VectorXd& confidence) const;

    // -----------------------------------------------------------------------
    // Diagnostics
    // -----------------------------------------------------------------------
    struct KellyDiagnostics {
        Eigen::VectorXd raw_kelly;          // before clamping
        Eigen::VectorXd clamped_kelly;      // after clamp(f_i, 0, f_max)
        Eigen::VectorXd risk_budgets;       // normalised
        Eigen::VectorXd final_weights;      // risk-parity adjusted
        double implied_leverage = 0.0;      // sum(|w_i|)
        double effective_n = 0.0;           // 1 / sum(w_i^2) -- diversification
    };

    KellyDiagnostics compute_diagnostics(
        const Eigen::VectorXd& mu,
        const Eigen::VectorXd& sigma,
        const Eigen::VectorXd& confidence) const;

    const Config& config() const { return config_; }

private:
    Config config_;
};

} // namespace trade
