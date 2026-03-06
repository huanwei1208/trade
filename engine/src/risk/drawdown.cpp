#include "trade/risk/drawdown.h"

#include <algorithm>
#include <cmath>
#include <numeric>

namespace trade {

// ---------------------------------------------------------------------------
// Evaluate drawdown level and return required actions
// ---------------------------------------------------------------------------
// Combines three mechanisms:
//   A) Drawdown ladder (threshold-based deleveraging)
//   B) Volatility scaling (target_vol / realized_vol)
//   C) Limit-down lock handling (A-share specific)
DrawdownController::DrawdownAction DrawdownController::evaluate(
    const std::vector<double>& nav_series,
    const std::vector<double>& returns,
    const std::vector<LockInfo>& locks,
    const std::unordered_map<Symbol, double>& betas) const {

    DrawdownAction action;

    // --- A) Drawdown ladder ---
    if (!nav_series.empty()) {
        action.nav_peak = compute_peak(nav_series);
        action.nav_current = nav_series.back();
        action.current_drawdown = compute_drawdown(nav_series);
        action.level = classify_drawdown(action.current_drawdown);

        switch (action.level) {
            case DrawdownLevel::kNormal:
                action.target_exposure_multiplier = 1.0;
                action.single_stock_cap = 0.10;
                break;

            case DrawdownLevel::kLevel1:
                // >= 5%: freeze high-beta new entries, reduce exposure 10%
                action.target_exposure_multiplier = 1.0 - config_.level1_reduction;
                action.freeze_high_beta_new = true;
                action.single_stock_cap = 0.10;
                break;

            case DrawdownLevel::kLevel2:
                // >= 8%: reduce exposure 20%, cut lowest-confidence quartile
                action.target_exposure_multiplier = 1.0 - config_.level2_reduction;
                action.freeze_high_beta_new = true;
                action.cut_lowest_confidence_quartile = true;
                action.single_stock_cap = 0.10;
                break;

            case DrawdownLevel::kLevel3:
                // >= 12%: reduce exposure 40%, single-stock cap drops to 5%
                action.target_exposure_multiplier = 1.0 - config_.level3_reduction;
                action.freeze_high_beta_new = true;
                action.cut_lowest_confidence_quartile = true;
                action.single_stock_cap = config_.level3_single_stock_cap;
                break;

            case DrawdownLevel::kCapitalPreserve:
                // >= 15%: capital preservation mode - only close or hedge
                action.target_exposure_multiplier = 0.0;
                action.capital_preservation_mode = true;
                action.freeze_high_beta_new = true;
                action.cut_lowest_confidence_quartile = true;
                action.single_stock_cap = config_.level3_single_stock_cap;
                break;
        }
    }

    // --- B) Volatility scaling ---
    if (!returns.empty()) {
        VolScaling vs = compute_vol_scaling(returns);
        action.vol_scale = vs.clamped_scale;
    }

    // --- Effective multiplier: min of drawdown ladder and vol scaling ---
    action.effective_multiplier = std::min(action.target_exposure_multiplier,
                                           action.vol_scale);

    // --- C) Limit-down lock handling ---
    if (!locks.empty()) {
        int high_lock_count = 0;
        for (const auto& lock : locks) {
            if (lock.is_locked || lock.is_suspended) {
                action.locked_symbols.push_back(lock.symbol);
            }
            if (lock.lock_probability >= config_.lock_prob_threshold) {
                high_lock_count++;
            }
        }
        action.high_lock_prob_count = high_lock_count;

        // If any positions are locked, force minimum cash buffer
        if (!action.locked_symbols.empty()) {
            action.required_cash_buffer = config_.min_cash_buffer;
            // Reduce effective multiplier to accommodate cash buffer
            double max_invested = 1.0 - action.required_cash_buffer;
            action.effective_multiplier = std::min(action.effective_multiplier,
                                                    max_invested);
        }
    }

    return action;
}

// ---------------------------------------------------------------------------
// Compute drawdown from NAV series: (peak - current) / peak
// ---------------------------------------------------------------------------
// Returns the current drawdown (most recent NAV vs running peak),
// not the maximum historical drawdown.
double DrawdownController::compute_drawdown(const std::vector<double>& nav_series) {
    if (nav_series.empty()) return 0.0;

    double peak = nav_series.front();
    for (double nav : nav_series) {
        if (nav > peak) peak = nav;
    }

    double current = nav_series.back();
    if (peak <= 0.0) return 0.0;

    return (peak - current) / peak;
}

// ---------------------------------------------------------------------------
// Compute peak NAV from series
// ---------------------------------------------------------------------------
double DrawdownController::compute_peak(const std::vector<double>& nav_series) {
    if (nav_series.empty()) return 0.0;

    double peak = nav_series.front();
    for (double nav : nav_series) {
        if (nav > peak) peak = nav;
    }
    return peak;
}

// ---------------------------------------------------------------------------
// Classify drawdown level based on configured thresholds
// ---------------------------------------------------------------------------
DrawdownController::DrawdownLevel DrawdownController::classify_drawdown(
    double drawdown) const {

    if (drawdown >= config_.capital_preserve_threshold)
        return DrawdownLevel::kCapitalPreserve;
    if (drawdown >= config_.level3_threshold)
        return DrawdownLevel::kLevel3;
    if (drawdown >= config_.level2_threshold)
        return DrawdownLevel::kLevel2;
    if (drawdown >= config_.level1_threshold)
        return DrawdownLevel::kLevel1;
    return DrawdownLevel::kNormal;
}

// ---------------------------------------------------------------------------
// Compute volatility scaling factor
// ---------------------------------------------------------------------------
// scale = min(1.0, target_vol / realized_vol_20d)
// Floor at vol_scale_floor to avoid excessive deleveraging in transient spikes.
DrawdownController::VolScaling DrawdownController::compute_vol_scaling(
    const std::vector<double>& returns) const {

    VolScaling vs;
    vs.target_vol = config_.target_vol;
    vs.realized_vol_20d = realized_vol(returns, config_.realized_vol_window);

    if (vs.realized_vol_20d > 0.0) {
        vs.raw_scale = vs.target_vol / vs.realized_vol_20d;
    } else {
        vs.raw_scale = 1.0;
    }

    vs.clamped_scale = std::max(config_.vol_scale_floor,
                                 std::min(1.0, vs.raw_scale));

    return vs;
}

// ---------------------------------------------------------------------------
// Compute realised volatility (annualised) from daily returns
// ---------------------------------------------------------------------------
// Uses the trailing 'window' returns.  Vol = std(returns) * sqrt(252).
double DrawdownController::realized_vol(
    const std::vector<double>& returns, int window) {

    if (returns.empty() || window <= 1) return 0.0;

    int n = static_cast<int>(returns.size());
    int start = std::max(0, n - window);
    int count = n - start;

    if (count <= 1) return 0.0;

    // Mean
    double sum = 0.0;
    for (int i = start; i < n; ++i) {
        sum += returns[i];
    }
    double mean = sum / count;

    // Variance (sample variance with Bessel's correction)
    double sum_sq = 0.0;
    for (int i = start; i < n; ++i) {
        double diff = returns[i] - mean;
        sum_sq += diff * diff;
    }
    double variance = sum_sq / (count - 1);

    // Annualised volatility
    return std::sqrt(variance * 252.0);
}

// ---------------------------------------------------------------------------
// Adjust weights based on drawdown action
// ---------------------------------------------------------------------------
// Applies the effective multiplier from the drawdown evaluation, plus:
//   - Cuts lowest-confidence quartile if required (Level 2+)
//   - Caps high-beta entries if required (Level 1+)
//   - Caps single-stock weights at the level-appropriate cap
Eigen::VectorXd DrawdownController::adjust_weights(
    const Eigen::VectorXd& weights,
    const DrawdownAction& action,
    const Eigen::VectorXd& confidence,
    const Eigen::VectorXd& betas) const {

    int N = static_cast<int>(weights.size());
    if (N == 0) return weights;

    Eigen::VectorXd w = weights;

    // Capital preservation mode: close all positions
    if (action.capital_preservation_mode) {
        return Eigen::VectorXd::Zero(N);
    }

    // Cut lowest-confidence quartile (set their weights to zero)
    if (action.cut_lowest_confidence_quartile && confidence.size() == N) {
        // Find the 25th percentile of confidence scores
        std::vector<double> conf_sorted(N);
        for (int i = 0; i < N; ++i) {
            conf_sorted[i] = confidence(i);
        }
        std::sort(conf_sorted.begin(), conf_sorted.end());

        int q1_idx = N / 4;  // 25th percentile index
        double q1_threshold = conf_sorted[q1_idx];

        for (int i = 0; i < N; ++i) {
            if (confidence(i) <= q1_threshold) {
                w(i) = 0.0;
            }
        }
    }

    // Freeze high-beta entries: cap weights of high-beta stocks
    if (action.freeze_high_beta_new && betas.size() == N) {
        for (int i = 0; i < N; ++i) {
            if (betas(i) > config_.high_beta_threshold) {
                // Reduce high-beta positions by an additional 50%
                w(i) *= 0.5;
            }
        }
    }

    // Cap single-stock weights
    for (int i = 0; i < N; ++i) {
        double cap = action.single_stock_cap;
        if (std::abs(w(i)) > cap) {
            w(i) = (w(i) > 0) ? cap : -cap;
        }
    }

    // Apply effective multiplier (combination of drawdown ladder + vol scaling)
    w *= action.effective_multiplier;

    return w;
}

// ---------------------------------------------------------------------------
// Apply lock-related adjustments to weights
// ---------------------------------------------------------------------------
// - High lock-probability stocks: halve their position cap
// - Locked/suspended stocks: cannot be traded (leave weight unchanged for
//   existing positions, but mark them)
// - Force minimum cash buffer if any position is locked
Eigen::VectorXd DrawdownController::apply_lock_adjustments(
    const Eigen::VectorXd& weights,
    const std::vector<LockInfo>& locks,
    double single_stock_cap) const {

    int N = static_cast<int>(weights.size());
    if (N == 0 || locks.empty()) return weights;

    Eigen::VectorXd w = weights;

    // Build symbol-to-index map for matching locks to weight indices
    // (locks may be provided in any order, but should match weight order)
    int n_locks = static_cast<int>(locks.size());

    for (int i = 0; i < std::min(N, n_locks); ++i) {
        const auto& lock = locks[i];

        if (lock.is_locked || lock.is_suspended) {
            // Cannot trade locked/suspended stocks; keep existing position
            // but do not increase it.  In practice, this means we just
            // leave the weight as-is (or clamp to current if we were going
            // to increase).
            continue;
        }

        if (lock.lock_probability >= config_.lock_prob_threshold) {
            // High lock probability: halve the position cap
            double reduced_cap = single_stock_cap * config_.lock_cap_reduction;
            if (std::abs(w(i)) > reduced_cap) {
                w(i) = (w(i) > 0) ? reduced_cap : -reduced_cap;
            }
        }
    }

    // Force cash buffer: scale down all investable weights so that
    // total invested weight <= (1 - min_cash_buffer)
    bool has_locked = false;
    for (int i = 0; i < n_locks; ++i) {
        if (locks[i].is_locked || locks[i].is_suspended) {
            has_locked = true;
            break;
        }
    }

    if (has_locked) {
        double total_abs = w.cwiseAbs().sum();
        double max_invested = 1.0 - config_.min_cash_buffer;
        if (total_abs > max_invested && total_abs > 0.0) {
            w *= max_invested / total_abs;
        }
    }

    return w;
}

} // namespace trade
