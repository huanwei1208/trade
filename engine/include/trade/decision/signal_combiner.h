#pragma once

#include "trade/common/types.h"
#include "trade/decision/signal.h"

#include <Eigen/Dense>
#include <string>
#include <unordered_map>
#include <vector>

namespace trade {

// ============================================================================
// SignalCombiner: two-stage signal fusion engine
// ============================================================================
//
// Stage A -- Calibration:
//   Raw model output -> rolling z-score standardisation -> logistic squash.
//   This maps heterogeneous model outputs (e.g. regression residuals, rank
//   scores, probabilities) onto a comparable [-1, +1] scale.
//
//     z_i = (raw_i - mu_rolling) / sigma_rolling      (rolling 60-day)
//     calibrated_i = 2 / (1 + exp(-z_i)) - 1          (logistic -> [-1, 1])
//
// Stage B -- Weighted fusion:
//   w_m = ICIR_m * regime_fit_m * data_quality_m
//
//   - Base weight:      rolling 60-day Information Coefficient IR (rank IC /
//                        IC volatility).
//   - Regime fit:       multiplicative modifier [0.5, 1.5] reflecting how
//                        well the model performs in the current regime.
//   - Data quality:     discount for stale or sparse input features.
//   - Stability penalty: penalise unstable models (high turnover + recent
//                        drawdown in IC) by shrinking their weight.
//
// Conflict detection:
//   If the weighted mean alpha ~ 0 (|alpha| < threshold) AND model dispersion
//   is high (stdev of calibrated scores > dispersion_threshold), the signal is
//   marked as "conflict" and routed to the watchlist, not the trade list.
//
// Minimum confidence gate:
//   confidence >= 0.6 is required for a signal to be tradable.
//
class SignalCombiner {
public:
    // -----------------------------------------------------------------------
    // Configuration
    // -----------------------------------------------------------------------
    struct Config {
        // Calibration
        int zscore_lookback = 60;               // rolling window for z-score (days)

        // Weight computation
        int icir_lookback = 60;                 // rolling window for ICIR
        double regime_fit_floor = 0.5;          // minimum regime fit multiplier
        double regime_fit_cap = 1.5;            // maximum regime fit multiplier

        // Stability penalty: weight *= max(0, 1 - penalty_coeff * instability)
        double instability_penalty_coeff = 0.3;
        double turnover_threshold = 0.5;        // model IC turnover threshold
        double drawdown_threshold = 0.10;       // model IC drawdown threshold

        // Conflict detection
        double conflict_alpha_threshold = 0.05; // |weighted alpha| below this
        double conflict_dispersion_threshold = 0.30; // stdev of calibrated scores

        // Confidence gate
        double min_confidence = 0.6;
    };

    SignalCombiner();
    explicit SignalCombiner(Config cfg);

    // -----------------------------------------------------------------------
    // Per-model running statistics (maintained by update_weights)
    // -----------------------------------------------------------------------
    struct ModelMeta {
        std::string model_name;

        // Rolling statistics for calibration
        double rolling_mean = 0.0;          // rolling mean of raw scores
        double rolling_std = 1.0;           // rolling std of raw scores

        // Weight components
        double icir = 0.0;                  // rolling 60-day ICIR
        double regime_fit = 1.0;            // regime-dependent multiplier
        double data_quality = 1.0;          // data freshness / completeness
        double stability = 1.0;             // 1.0 = stable, penalised down

        // Derived
        double composite_weight = 0.0;      // final fused weight (normalised)
    };

    // -----------------------------------------------------------------------
    // Stage A: Calibration
    // -----------------------------------------------------------------------
    // Calibrate a vector of raw model scores to a comparable scale.
    //   raw_scores: (M,) raw outputs from M models for one symbol.
    //   model_metas: rolling statistics per model (updated externally).
    // Returns: (M,) calibrated scores in approximately [-1, 1].
    Eigen::VectorXd calibrate(
        const Eigen::VectorXd& raw_scores,
        const std::vector<ModelMeta>& model_metas) const;

    // -----------------------------------------------------------------------
    // Stage B: Weighted fusion -> Signal
    // -----------------------------------------------------------------------
    // Combine calibrated scores into a single Signal for a symbol.
    //   symbol:           the ticker
    //   calibrated_scores: (M,) from calibrate()
    //   regime:           current market regime
    //   model_metas:      per-model metadata (weights, names, etc.)
    //   sentiment:        optional sentiment overlay
    // Returns: a fully populated Signal struct.
    Signal combine(
        const Symbol& symbol,
        const Eigen::VectorXd& calibrated_scores,
        Regime regime,
        const std::vector<ModelMeta>& model_metas,
        const Signal::SentimentOverlay& sentiment = {}) const;

    // -----------------------------------------------------------------------
    // Batch interface: fuse signals for an entire cross-section
    // -----------------------------------------------------------------------
    // raw_matrix: (N x M) -- N symbols, M models, each cell is raw score.
    // symbols:    (N,) ticker list
    // Returns: vector of N Signal objects.
    std::vector<Signal> combine_batch(
        const std::vector<Symbol>& symbols,
        const Eigen::MatrixXd& raw_matrix,
        Regime regime,
        const std::vector<ModelMeta>& model_metas,
        const std::unordered_map<Symbol, Signal::SentimentOverlay>& sentiments = {}) const;

    // -----------------------------------------------------------------------
    // Weight update: recalibrate model weights from recent performance
    // -----------------------------------------------------------------------
    // Called periodically (e.g. daily) with actual IC observations.
    //   model_metas:        in/out -- updated in place
    //   recent_ic_matrix:   (T x M) -- T recent days of rank IC per model
    //   regime:             current market regime
    void update_weights(
        std::vector<ModelMeta>& model_metas,
        const Eigen::MatrixXd& recent_ic_matrix,
        Regime regime) const;

    const Config& config() const { return config_; }

private:
    Config config_;

    // Logistic squash: maps z to [-1, +1]
    static double logistic_squash(double z);

    // Compute dispersion (standard deviation) of calibrated scores
    static double score_dispersion(const Eigen::VectorXd& calibrated_scores);

    // Derive confidence from alpha magnitude and dispersion
    static double compute_confidence(double alpha, double dispersion);

    // Normalise raw weights so they sum to 1
    static Eigen::VectorXd normalise_weights(const Eigen::VectorXd& raw_weights);
};

} // namespace trade
