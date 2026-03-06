#include "trade/decision/signal_combiner.h"

#include <cmath>
#include <numeric>

namespace trade {

// ---------------------------------------------------------------------------
// Constructors
// ---------------------------------------------------------------------------

SignalCombiner::SignalCombiner() : config_{} {}
SignalCombiner::SignalCombiner(Config cfg) : config_(cfg) {}

Eigen::VectorXd SignalCombiner::calibrate(
    const Eigen::VectorXd& raw_scores,
    const std::vector<ModelMeta>& model_metas) const {
    int m = static_cast<int>(raw_scores.size());
    Eigen::VectorXd calibrated(m);

    for (int i = 0; i < m; ++i) {
        double z = (model_metas[i].rolling_std > 0.0)
                     ? (raw_scores(i) - model_metas[i].rolling_mean) / model_metas[i].rolling_std
                     : 0.0;
        calibrated(i) = logistic_squash(z);
    }
    return calibrated;
}

Signal SignalCombiner::combine(
    const Symbol& symbol,
    const Eigen::VectorXd& calibrated_scores,
    Regime regime,
    const std::vector<ModelMeta>& model_metas,
    const Signal::SentimentOverlay& sentiment) const {

    int m = static_cast<int>(calibrated_scores.size());

    // Build weight vector from model metas
    Eigen::VectorXd raw_weights(m);
    for (int i = 0; i < m; ++i) {
        raw_weights(i) = model_metas[i].composite_weight;
    }
    Eigen::VectorXd weights = normalise_weights(raw_weights);

    // Weighted alpha
    double alpha = weights.dot(calibrated_scores);
    double dispersion = score_dispersion(calibrated_scores);
    double confidence = compute_confidence(alpha, dispersion);

    // Conflict detection
    bool is_conflict = (std::abs(alpha) < config_.conflict_alpha_threshold &&
                        dispersion > config_.conflict_dispersion_threshold);

    Signal signal;
    signal.symbol = symbol;
    signal.alpha_score = alpha;
    signal.confidence = confidence;
    signal.regime = regime;
    signal.is_conflict = is_conflict;
    signal.sentiment = sentiment;

    // Per-model breakdown
    for (int i = 0; i < m; ++i) {
        Signal::ModelScore ms;
        ms.model_name = model_metas[i].model_name;
        ms.raw_score = 0.0;  // Not available at this stage
        ms.calibrated_score = calibrated_scores(i);
        ms.weight = weights(i);
        signal.model_scores.push_back(ms);
    }

    return signal;
}

std::vector<Signal> SignalCombiner::combine_batch(
    const std::vector<Symbol>& symbols,
    const Eigen::MatrixXd& raw_matrix,
    Regime regime,
    const std::vector<ModelMeta>& model_metas,
    const std::unordered_map<Symbol, Signal::SentimentOverlay>& sentiments) const {

    int n = static_cast<int>(symbols.size());
    std::vector<Signal> signals;
    signals.reserve(n);

    for (int i = 0; i < n; ++i) {
        Eigen::VectorXd raw_row = raw_matrix.row(i);
        Eigen::VectorXd calibrated = calibrate(raw_row, model_metas);

        Signal::SentimentOverlay overlay;
        auto it = sentiments.find(symbols[i]);
        if (it != sentiments.end()) {
            overlay = it->second;
        }

        signals.push_back(combine(symbols[i], calibrated, regime, model_metas, overlay));
    }

    return signals;
}

void SignalCombiner::update_weights(
    std::vector<ModelMeta>& model_metas,
    const Eigen::MatrixXd& recent_ic_matrix,
    Regime /*regime*/) const {

    int m = static_cast<int>(model_metas.size());
    if (m == 0) return;

    for (int j = 0; j < m; ++j) {
        auto& meta = model_metas[j];

        // Compute ICIR from recent_ic_matrix column j
        if (recent_ic_matrix.rows() > 0 && j < recent_ic_matrix.cols()) {
            Eigen::VectorXd ic_col = recent_ic_matrix.col(j);
            double mean_ic = ic_col.mean();
            double std_ic = 0.0;
            if (ic_col.size() > 1) {
                double var = (ic_col.array() - mean_ic).square().sum()
                             / static_cast<double>(ic_col.size() - 1);
                std_ic = std::sqrt(var);
            }
            meta.icir = (std_ic > 0.0) ? mean_ic / std_ic : 0.0;
        }

        // Composite weight: ICIR * regime_fit * data_quality * stability
        double w = std::abs(meta.icir) * meta.regime_fit
                   * meta.data_quality * meta.stability;
        meta.composite_weight = w;
    }

    // Normalise composite weights
    double total = 0.0;
    for (const auto& meta : model_metas) {
        total += meta.composite_weight;
    }
    if (total > 0.0) {
        for (auto& meta : model_metas) {
            meta.composite_weight /= total;
        }
    }
}

double SignalCombiner::logistic_squash(double z) {
    // Maps z to [-1, +1]: 2 / (1 + exp(-z)) - 1
    return 2.0 / (1.0 + std::exp(-z)) - 1.0;
}

double SignalCombiner::score_dispersion(const Eigen::VectorXd& calibrated_scores) {
    if (calibrated_scores.size() <= 1) return 0.0;
    double mean = calibrated_scores.mean();
    double var = (calibrated_scores.array() - mean).square().sum()
                 / static_cast<double>(calibrated_scores.size());
    return std::sqrt(var);
}

double SignalCombiner::compute_confidence(double alpha, double dispersion) {
    // Confidence increases with alpha magnitude, decreases with dispersion
    double raw = std::abs(alpha) / (1.0 + dispersion);
    // Map to [0, 1] via sigmoid-like transform
    return 2.0 / (1.0 + std::exp(-5.0 * raw)) - 1.0;
}

Eigen::VectorXd SignalCombiner::normalise_weights(const Eigen::VectorXd& raw_weights) {
    double sum = raw_weights.sum();
    if (sum <= 0.0) {
        // Equal weights if all zero
        int n = static_cast<int>(raw_weights.size());
        if (n == 0) return {};
        return Eigen::VectorXd::Constant(n, 1.0 / n);
    }
    return raw_weights / sum;
}

} // namespace trade
