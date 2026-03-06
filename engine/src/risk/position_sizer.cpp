#include "trade/risk/position_sizer.h"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <unordered_map>
#include <vector>

namespace trade {

// ---------------------------------------------------------------------------
// Main constraint-aware position sizing
// ---------------------------------------------------------------------------
// Iterative clamp-and-rescale: each iteration enforces all constraints in
// sequence.  Excess weight from clamped positions is redistributed pro-rata
// to unclamped positions.  The loop terminates when weights converge or
// max_iterations is reached.
PositionSizer::SizingResult PositionSizer::size_positions(
    const Eigen::VectorXd& alphas,
    const std::vector<StockRisk>& risks,
    const Eigen::MatrixXd& factor_loadings,
    const Eigen::MatrixXd& cov) const {

    int N = static_cast<int>(alphas.size());
    SizingResult result;
    result.symbols.resize(N);
    result.weights = Eigen::VectorXd::Zero(N);

    if (N == 0) {
        result.converged = true;
        return result;
    }

    // Collect metadata vectors
    std::vector<SWIndustry> industries(N, SWIndustry::kUnknown);
    Eigen::VectorXd betas = Eigen::VectorXd::Ones(N);
    Eigen::VectorXd adv_vec = Eigen::VectorXd::Zero(N);
    Eigen::VectorXd vol_vec = Eigen::VectorXd::Zero(N);

    for (int i = 0; i < N; ++i) {
        if (i < static_cast<int>(risks.size())) {
            result.symbols[i] = risks[i].symbol;
            industries[i] = risks[i].industry;
            betas(i) = risks[i].beta;
            adv_vec(i) = risks[i].adv_20d;
            vol_vec(i) = risks[i].annualised_vol;
        }
    }

    // Initial weights: proportional to alpha scores, normalised to sum |w| = 1
    Eigen::VectorXd w = alphas;
    double sum_abs = w.cwiseAbs().sum();
    if (sum_abs > 1e-15) {
        w /= sum_abs;
    }

    // Iterative constraint enforcement
    int iter = 0;
    bool converged = false;

    for (iter = 0; iter < constraints_.max_iterations; ++iter) {
        Eigen::VectorXd w_prev = w;

        // ---- Constraint 1: Single-stock weight cap ----
        w = clamp_single_stock(w, constraints_.single_stock_hard_pct);

        // ---- Constraint 2: Volatility-bucket caps ----
        for (int i = 0; i < N; ++i) {
            double cap = vol_bucket_cap(vol_vec(i));
            if (std::abs(w(i)) > cap) {
                w(i) = (w(i) > 0) ? cap : -cap;
            }
        }

        // ---- Constraint 3: Industry concentration ----
        w = clamp_industry(w, industries, constraints_.industry_hard_pct);

        // ---- Constraint 4: Top-N combined weight ----
        w = clamp_top_n(w, constraints_.top_n, constraints_.top_n_combined_pct);

        // ---- Constraint 5: Liquidity constraint ----
        // position <= liquidity_adv_fraction * ADV
        // With NAV = 1 (weights are fractions of NAV), position = |w_i| * NAV
        for (int i = 0; i < N; ++i) {
            if (adv_vec(i) > 0.0) {
                double max_weight = constraints_.liquidity_adv_fraction * adv_vec(i);
                // max_weight is in notional; since w is fraction of NAV (=1),
                // we clamp directly
                if (std::abs(w(i)) > max_weight && max_weight > 0.0) {
                    w(i) = (w(i) > 0) ? max_weight : -max_weight;
                }
            }
        }

        // ---- Constraint 6: Factor exposure bounds ----
        if (factor_loadings.rows() == N && factor_loadings.cols() > 0) {
            int K = static_cast<int>(factor_loadings.cols());
            Eigen::VectorXd port_exposure = factor_loadings.transpose() * w;

            for (int k = 0; k < K; ++k) {
                double exp_k = port_exposure(k);
                double limit = constraints_.factor_exposure_abs_max;
                if (std::abs(exp_k) > limit) {
                    // Scale down all weights proportionally to bring exposure
                    // within bounds
                    double scale_factor = limit / std::abs(exp_k);
                    // Only scale factor-exposed assets: use a soft scaling approach
                    // to avoid distorting the entire portfolio
                    Eigen::VectorXd loadings_k = factor_loadings.col(k);
                    for (int i = 0; i < N; ++i) {
                        if (std::abs(loadings_k(i)) > 1e-10) {
                            // Scale down assets with high factor loading
                            double contrib = std::abs(loadings_k(i));
                            double dampen = 1.0 - (1.0 - scale_factor) * contrib /
                                            loadings_k.cwiseAbs().maxCoeff();
                            dampen = std::max(0.0, std::min(1.0, dampen));
                            w(i) *= dampen;
                        }
                    }
                }
            }
        }

        // ---- Constraint 7: Portfolio Beta bounds ----
        w = adjust_beta(w, betas, constraints_.beta_min, constraints_.beta_max);

        // ---- Re-normalise to sum(|w|) = 1 ----
        sum_abs = w.cwiseAbs().sum();
        if (sum_abs > 1e-15) {
            w /= sum_abs;
        }

        // Check convergence
        double delta = (w - w_prev).squaredNorm();
        if (delta < constraints_.convergence_tol * constraints_.convergence_tol) {
            converged = true;
            break;
        }
    }

    result.weights = w;
    result.iterations_used = iter + 1;
    result.converged = converged;

    // Compute diagnostics
    result.gross_exposure = w.cwiseAbs().sum();
    result.max_single_stock = w.cwiseAbs().maxCoeff();

    // Portfolio beta
    result.portfolio_beta = w.dot(betas);

    // Max industry weight
    std::unordered_map<int, double> ind_weights;
    for (int i = 0; i < N; ++i) {
        ind_weights[static_cast<int>(industries[i])] += std::abs(w(i));
    }
    result.max_industry_weight = 0.0;
    for (auto& [ind, wt] : ind_weights) {
        result.max_industry_weight = std::max(result.max_industry_weight, wt);
    }

    // Top-N combined
    Eigen::VectorXd abs_w = w.cwiseAbs();
    std::vector<double> sorted_w(abs_w.data(), abs_w.data() + N);
    std::sort(sorted_w.rbegin(), sorted_w.rend());
    result.top_n_combined = 0.0;
    for (int i = 0; i < std::min(constraints_.top_n, N); ++i) {
        result.top_n_combined += sorted_w[i];
    }

    // Liquidation days
    result.liquidation_days = compute_liquidation_days(w, adv_vec, 1.0);

    // Count violations (against soft limits, before resolution)
    for (int i = 0; i < N; ++i) {
        if (std::abs(w(i)) > constraints_.single_stock_soft_pct) {
            result.violations.single_stock++;
        }
        double cap = vol_bucket_cap(vol_vec(i));
        // Use the softer cap range lower bound for violation check
        if (vol_vec(i) < constraints_.low_vol_threshold) {
            if (std::abs(w(i)) > constraints_.low_vol_cap_min)
                result.violations.vol_bucket++;
        } else if (vol_vec(i) > constraints_.high_vol_threshold) {
            if (std::abs(w(i)) > constraints_.high_vol_cap_min)
                result.violations.vol_bucket++;
        } else {
            if (std::abs(w(i)) > constraints_.mid_vol_cap_min)
                result.violations.vol_bucket++;
        }
    }
    for (auto& [ind, wt] : ind_weights) {
        if (wt > constraints_.industry_soft_pct) {
            result.violations.industry++;
        }
    }
    if (result.top_n_combined > constraints_.top_n_combined_pct) {
        result.violations.top_n = 1;
    }
    if (result.portfolio_beta < constraints_.beta_min ||
        result.portfolio_beta > constraints_.beta_max) {
        result.violations.beta = 1;
    }
    if (result.liquidation_days > constraints_.max_liquidation_days) {
        result.violations.liquidation = 1;
    }

    return result;
}

// ---------------------------------------------------------------------------
// Clamp single-stock weights to hard limit
// ---------------------------------------------------------------------------
Eigen::VectorXd PositionSizer::clamp_single_stock(
    const Eigen::VectorXd& weights, double hard_pct) {

    int N = static_cast<int>(weights.size());
    Eigen::VectorXd w = weights;

    for (int i = 0; i < N; ++i) {
        if (w(i) > hard_pct) {
            w(i) = hard_pct;
        } else if (w(i) < -hard_pct) {
            w(i) = -hard_pct;
        }
    }

    return w;
}

// ---------------------------------------------------------------------------
// Clamp industry exposures
// ---------------------------------------------------------------------------
// For each industry, if the sum of |weights| exceeds hard_pct, scale down
// all positions in that industry proportionally.
Eigen::VectorXd PositionSizer::clamp_industry(
    const Eigen::VectorXd& weights,
    const std::vector<SWIndustry>& industries,
    double hard_pct) {

    int N = static_cast<int>(weights.size());
    Eigen::VectorXd w = weights;

    // Group by industry
    std::unordered_map<int, std::vector<int>> industry_members;
    for (int i = 0; i < N; ++i) {
        int ind = (i < static_cast<int>(industries.size()))
                    ? static_cast<int>(industries[i])
                    : static_cast<int>(SWIndustry::kUnknown);
        industry_members[ind].push_back(i);
    }

    // For each industry, check and scale down if needed
    for (auto& [ind, members] : industry_members) {
        double total_abs = 0.0;
        for (int idx : members) {
            total_abs += std::abs(w(idx));
        }

        if (total_abs > hard_pct) {
            double scale = hard_pct / total_abs;
            for (int idx : members) {
                w(idx) *= scale;
            }
        }
    }

    return w;
}

// ---------------------------------------------------------------------------
// Clamp top-N combined weight
// ---------------------------------------------------------------------------
// If the sum of the N largest |weights| exceeds max_combined, scale down
// just those positions proportionally.
Eigen::VectorXd PositionSizer::clamp_top_n(
    const Eigen::VectorXd& weights, int n, double max_combined) {

    int N = static_cast<int>(weights.size());
    if (N <= 0 || n <= 0) return weights;

    Eigen::VectorXd w = weights;

    // Find indices of top-n positions by absolute weight
    std::vector<int> indices(N);
    std::iota(indices.begin(), indices.end(), 0);
    std::partial_sort(indices.begin(),
                      indices.begin() + std::min(n, N),
                      indices.end(),
                      [&w](int a, int b) {
                          return std::abs(w(a)) > std::abs(w(b));
                      });

    int top_count = std::min(n, N);
    double top_sum = 0.0;
    for (int i = 0; i < top_count; ++i) {
        top_sum += std::abs(w(indices[i]));
    }

    if (top_sum > max_combined) {
        double scale = max_combined / top_sum;
        for (int i = 0; i < top_count; ++i) {
            w(indices[i]) *= scale;
        }
    }

    return w;
}

// ---------------------------------------------------------------------------
// Adjust weights to satisfy portfolio Beta bounds
// ---------------------------------------------------------------------------
// If portfolio beta = sum(w_i * beta_i) is outside [beta_min, beta_max],
// shift weights towards/away from high-beta stocks to bring beta in range.
Eigen::VectorXd PositionSizer::adjust_beta(
    const Eigen::VectorXd& weights,
    const Eigen::VectorXd& betas,
    double beta_min, double beta_max) {

    int N = static_cast<int>(weights.size());
    if (N == 0 || betas.size() != N) return weights;

    Eigen::VectorXd w = weights;
    double port_beta = w.dot(betas);

    // If beta is within bounds, no adjustment needed
    if (port_beta >= beta_min && port_beta <= beta_max) {
        return w;
    }

    // Strategy: scale high-beta vs low-beta positions to adjust portfolio beta.
    // Compute the average beta
    double avg_beta = betas.mean();
    if (std::abs(avg_beta) < 1e-10) return w;

    // We want to find a scalar t such that the new portfolio beta is in range.
    // New weights: w_i' = w_i * (1 + t * (beta_i - avg_beta))
    // New beta: sum(w_i' * beta_i) = target_beta
    // This is an iterative adjustment
    double target_beta = (port_beta < beta_min) ? beta_min : beta_max;

    // Gradient: d(port_beta) / dt = sum(w_i * beta_i * (beta_i - avg_beta))
    double gradient = 0.0;
    for (int i = 0; i < N; ++i) {
        gradient += w(i) * betas(i) * (betas(i) - avg_beta);
    }

    if (std::abs(gradient) > 1e-15) {
        double t = (target_beta - port_beta) / gradient;
        // Limit the adjustment to avoid extreme distortions
        t = std::max(-0.5, std::min(0.5, t));

        for (int i = 0; i < N; ++i) {
            double factor = 1.0 + t * (betas(i) - avg_beta);
            factor = std::max(0.0, factor);  // do not flip signs
            w(i) *= factor;
        }
    }

    return w;
}

// ---------------------------------------------------------------------------
// Compute liquidation days: max_i(|w_i * NAV| / adv_i)
// ---------------------------------------------------------------------------
double PositionSizer::compute_liquidation_days(
    const Eigen::VectorXd& weights,
    const Eigen::VectorXd& adv,
    double nav) {

    int N = static_cast<int>(weights.size());
    if (N == 0 || adv.size() != N) return 0.0;

    double max_days = 0.0;
    for (int i = 0; i < N; ++i) {
        if (adv(i) > 0.0) {
            double position_notional = std::abs(weights(i)) * nav;
            double days = position_notional / adv(i);
            max_days = std::max(max_days, days);
        }
    }

    return max_days;
}

// ---------------------------------------------------------------------------
// Volatility bucket cap: per-stock max weight based on vol regime
// ---------------------------------------------------------------------------
double PositionSizer::vol_bucket_cap(double annualised_vol) const {
    if (annualised_vol < constraints_.low_vol_threshold) {
        return constraints_.low_vol_cap_max;
    }
    if (annualised_vol > constraints_.high_vol_threshold) {
        return constraints_.high_vol_cap_max;
    }
    return constraints_.mid_vol_cap_max;
}

} // namespace trade
