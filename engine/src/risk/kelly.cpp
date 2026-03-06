#include "trade/risk/kelly.h"

#include <cmath>

namespace trade {

// ---------------------------------------------------------------------------
// Step 1: Raw Kelly fractions
// ---------------------------------------------------------------------------
// f_i = kelly_fraction_multiplier * mu_i / sigma_i^2
// The classical Kelly criterion says f* = mu / sigma^2.  We use a fraction
// (typically 0.25 = "quarter Kelly") for conservatism.
// The sign of mu determines long/short: positive mu => long, negative => short.
Eigen::VectorXd KellyCalculator::kelly_fraction(
    const Eigen::VectorXd& mu,
    const Eigen::VectorXd& sigma) const {

    int N = static_cast<int>(mu.size());
    Eigen::VectorXd result = Eigen::VectorXd::Zero(N);

    for (int i = 0; i < N; ++i) {
        double sig = sigma(i);
        if (sig > 1e-10) {
            double var = sig * sig;
            result(i) = config_.kelly_fraction * mu(i) / var;
        }
        // If sigma is near zero, f stays at 0 (undefined signal, skip)
    }

    return result;
}

// ---------------------------------------------------------------------------
// Step 2: Risk budget allocation
// ---------------------------------------------------------------------------
// rb_i proportional to clamp(f_i, 0, f_max) * confidence_i
// Normalised so that sum(rb_i) = 1 over all active assets (rb_i > 0).
// Assets with negative Kelly fraction or confidence below min_confidence
// are excluded (set to 0).
Eigen::VectorXd KellyCalculator::risk_budget(
    const Eigen::VectorXd& kelly,
    const Eigen::VectorXd& confidence) const {

    int N = static_cast<int>(kelly.size());
    Eigen::VectorXd rb = Eigen::VectorXd::Zero(N);

    for (int i = 0; i < N; ++i) {
        // Clamp Kelly fraction to [0, f_max].  We only budget for positive
        // (long) signals here; short signals would need a separate book.
        double f_clamped = std::max(0.0, std::min(config_.f_max, kelly(i)));

        // Confidence gate
        double conf = (i < confidence.size()) ? confidence(i) : 1.0;
        if (conf < config_.min_confidence) {
            f_clamped = 0.0;
        }

        rb(i) = f_clamped * conf;
    }

    // Normalise so sum = 1
    double total = rb.sum();
    if (total > 1e-15) {
        rb /= total;
    }

    return rb;
}

// ---------------------------------------------------------------------------
// Step 3: Risk-parity adjusted weights
// ---------------------------------------------------------------------------
// w_i proportional to rb_i / sigma_i
// This ensures each asset contributes roughly equal risk per unit of budget.
// Final weights are normalised to sum to target_gross_exposure.
Eigen::VectorXd KellyCalculator::risk_parity_weights(
    const Eigen::VectorXd& risk_bgt,
    const Eigen::VectorXd& sigma) const {

    int N = static_cast<int>(risk_bgt.size());
    Eigen::VectorXd w = Eigen::VectorXd::Zero(N);

    for (int i = 0; i < N; ++i) {
        double sig = (i < sigma.size()) ? sigma(i) : 1.0;
        if (sig > 1e-10 && risk_bgt(i) > 0.0) {
            w(i) = risk_bgt(i) / sig;
        }
    }

    // Normalise to target gross exposure
    double sum_abs = w.cwiseAbs().sum();
    if (sum_abs > 1e-15) {
        w *= config_.target_gross_exposure / sum_abs;
    }

    return w;
}

// ---------------------------------------------------------------------------
// Convenience: full pipeline in one call
// ---------------------------------------------------------------------------
Eigen::VectorXd KellyCalculator::compute_weights(
    const Eigen::VectorXd& mu,
    const Eigen::VectorXd& sigma,
    const Eigen::VectorXd& confidence) const {

    Eigen::VectorXd kf = kelly_fraction(mu, sigma);
    Eigen::VectorXd rb = risk_budget(kf, confidence);
    return risk_parity_weights(rb, sigma);
}

// ---------------------------------------------------------------------------
// Diagnostics: full pipeline with intermediate outputs
// ---------------------------------------------------------------------------
KellyCalculator::KellyDiagnostics KellyCalculator::compute_diagnostics(
    const Eigen::VectorXd& mu,
    const Eigen::VectorXd& sigma,
    const Eigen::VectorXd& confidence) const {

    KellyDiagnostics diag;
    int N = static_cast<int>(mu.size());

    // Step 1: raw Kelly fractions
    diag.raw_kelly = kelly_fraction(mu, sigma);

    // Step 1b: clamped Kelly (before weighting by confidence)
    diag.clamped_kelly = Eigen::VectorXd::Zero(N);
    for (int i = 0; i < N; ++i) {
        diag.clamped_kelly(i) = std::max(0.0,
                                         std::min(config_.f_max, diag.raw_kelly(i)));
    }

    // Step 2: risk budgets
    diag.risk_budgets = risk_budget(diag.raw_kelly, confidence);

    // Step 3: final weights
    diag.final_weights = risk_parity_weights(diag.risk_budgets, sigma);

    // Implied leverage: sum(|w_i|)
    diag.implied_leverage = diag.final_weights.cwiseAbs().sum();

    // Effective N: 1 / sum(w_i^2)  -- a measure of diversification
    double sum_sq = diag.final_weights.squaredNorm();
    diag.effective_n = (sum_sq > 1e-15) ? 1.0 / sum_sq : 0.0;

    return diag;
}

} // namespace trade
