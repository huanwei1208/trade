#include "trade/decision/portfolio_opt.h"

#include <algorithm>
#include <cmath>
#include <numeric>

namespace trade {

// ---------------------------------------------------------------------------
// Constructors
// ---------------------------------------------------------------------------

PortfolioOptimizer::PortfolioOptimizer() : constraints_{} {}
PortfolioOptimizer::PortfolioOptimizer(Constraints constraints) : constraints_(constraints) {}

PortfolioOptimizer::OptimizationResult PortfolioOptimizer::optimize(
    const std::vector<Candidate>& candidates,
    const std::unordered_map<Symbol, double>& current_weights,
    const Eigen::MatrixXd& covariance,
    const Eigen::MatrixXd& factor_loadings,
    const Eigen::VectorXd& betas) const {

    int k = static_cast<int>(candidates.size());
    if (k == 0) {
        OptimizationResult result;
        result.converged = true;
        return result;
    }

    // Build alpha and cost vectors
    Eigen::VectorXd alpha_vec(k);
    Eigen::VectorXd cost_vec(k);
    Eigen::VectorXd current_w(k);
    std::vector<SWIndustry> industries(k);

    Eigen::VectorXd beta_vec;
    if (betas.size() == k) {
        beta_vec = betas;
    } else {
        beta_vec = Eigen::VectorXd::Ones(k);
        for (int i = 0; i < k; ++i) {
            beta_vec(i) = candidates[i].beta;
        }
    }

    for (int i = 0; i < k; ++i) {
        alpha_vec(i) = candidates[i].alpha;
        cost_vec(i) = candidates[i].estimated_cost / 10000.0;  // bps -> fraction
        industries[i] = candidates[i].industry;

        auto it = current_weights.find(candidates[i].symbol);
        current_w(i) = (it != current_weights.end()) ? it->second : 0.0;
    }

    // Solve using internal QP solver
    auto result = solve_qp(alpha_vec, cost_vec, covariance, current_w,
                           factor_loadings, beta_vec, industries);

    // Populate symbols
    result.symbols.resize(k);
    for (int i = 0; i < k; ++i) {
        result.symbols[i] = candidates[i].symbol;
    }

    // Generate trade instructions
    result.trades = generate_trades(result.symbols, result.target_weights,
                                     current_weights);

    return result;
}

std::vector<PortfolioOptimizer::Candidate> PortfolioOptimizer::select_candidates(
    const std::vector<Signal>& signals,
    const std::unordered_map<Symbol, double>& cost_estimates,
    const std::unordered_map<Symbol, double>& betas,
    const std::unordered_map<Symbol, SWIndustry>& industries,
    const std::unordered_map<Symbol, double>& adv_20d,
    double alpha_cost_multiple,
    int max_k) {

    std::vector<Candidate> candidates;

    for (const auto& sig : signals) {
        if (!sig.is_tradable()) continue;

        double cost = 0.0;
        auto cost_it = cost_estimates.find(sig.symbol);
        if (cost_it != cost_estimates.end()) cost = cost_it->second;

        // Alpha must exceed cost * multiple to qualify
        if (std::abs(sig.alpha_score) < cost * alpha_cost_multiple / 10000.0) {
            continue;
        }

        Candidate c;
        c.symbol = sig.symbol;
        c.alpha = sig.alpha_score;
        c.confidence = sig.confidence;
        c.estimated_cost = cost;

        auto beta_it = betas.find(sig.symbol);
        c.beta = (beta_it != betas.end()) ? beta_it->second : 1.0;

        auto ind_it = industries.find(sig.symbol);
        c.industry = (ind_it != industries.end()) ? ind_it->second : SWIndustry::kUnknown;

        auto adv_it = adv_20d.find(sig.symbol);
        c.adv_20d = (adv_it != adv_20d.end()) ? adv_it->second : 0.0;

        candidates.push_back(c);
    }

    // Sort by alpha - cost (descending)
    std::sort(candidates.begin(), candidates.end(),
              [](const Candidate& a, const Candidate& b) {
                  return (a.alpha - a.estimated_cost / 10000.0) >
                         (b.alpha - b.estimated_cost / 10000.0);
              });

    // Take top K
    if (static_cast<int>(candidates.size()) > max_k) {
        candidates.resize(max_k);
    }

    return candidates;
}

std::vector<PortfolioOptimizer::TradeInstruction> PortfolioOptimizer::generate_trades(
    const std::vector<Symbol>& symbols,
    const Eigen::VectorXd& target_weights,
    const std::unordered_map<Symbol, double>& current_weights,
    double rebalance_threshold) {

    std::vector<TradeInstruction> trades;
    int k = static_cast<int>(symbols.size());

    for (int i = 0; i < k; ++i) {
        double current = 0.0;
        auto it = current_weights.find(symbols[i]);
        if (it != current_weights.end()) current = it->second;

        double target = target_weights(i);
        double delta = target - current;

        if (std::abs(delta) < rebalance_threshold) continue;

        TradeInstruction ti;
        ti.symbol = symbols[i];
        ti.side = (delta > 0) ? Side::kBuy : Side::kSell;
        ti.target_weight = target;
        ti.current_weight = current;
        ti.delta_weight = delta;
        ti.reason = (delta > 0) ? "increase position" : "reduce position";
        trades.push_back(ti);
    }

    // Also generate sells for positions not in the target
    for (const auto& [sym, w] : current_weights) {
        if (w <= rebalance_threshold) continue;
        bool found = false;
        for (const auto& s : symbols) {
            if (s == sym) { found = true; break; }
        }
        if (!found) {
            TradeInstruction ti;
            ti.symbol = sym;
            ti.side = Side::kSell;
            ti.target_weight = 0.0;
            ti.current_weight = w;
            ti.delta_weight = -w;
            ti.reason = "exit position";
            trades.push_back(ti);
        }
    }

    return trades;
}

PortfolioOptimizer::OptimizationResult PortfolioOptimizer::solve_qp(
    const Eigen::VectorXd& alpha_vec,
    const Eigen::VectorXd& cost_vec,
    const Eigen::MatrixXd& covariance,
    const Eigen::VectorXd& current_w,
    const Eigen::MatrixXd& factor_loadings,
    const Eigen::VectorXd& betas,
    const std::vector<SWIndustry>& industries) const {

    int k = static_cast<int>(alpha_vec.size());
    OptimizationResult result;
    result.target_weights = Eigen::VectorXd::Zero(k);

    if (k == 0) {
        result.converged = true;
        return result;
    }

    double target_sum = 1.0 - constraints_.cash_floor;
    bool has_cov = (covariance.rows() == k && covariance.cols() == k);

    // -----------------------------------------------------------------------
    // Step 1: Risk-parity initialisation  (w_i proportional to 1/sigma_i)
    // -----------------------------------------------------------------------
    Eigen::VectorXd sigma(k);
    if (has_cov) {
        for (int i = 0; i < k; ++i) {
            sigma(i) = std::sqrt(std::max(covariance(i, i), 1e-12));
        }
    } else {
        sigma = Eigen::VectorXd::Ones(k);
    }

    Eigen::VectorXd inv_sigma(k);
    for (int i = 0; i < k; ++i) {
        inv_sigma(i) = 1.0 / std::max(sigma(i), 1e-12);
    }

    Eigen::VectorXd w = inv_sigma;
    double sum = w.sum();
    if (sum > 0.0) {
        w *= target_sum / sum;
    }

    // -----------------------------------------------------------------------
    // Step 2: Gradient projection iterations
    //   objective: max  w'*alpha - w'*cost - lambda * w'*Sigma*w
    //              - turnover_penalty * |w - w_current|
    //   gradient:  alpha - cost - 2*lambda*Sigma*w
    //   project onto constraint set after each step.
    // -----------------------------------------------------------------------
    constexpr int max_iter = 200;
    constexpr double tol = 1e-8;
    double step_size = 0.01;
    double lambda = constraints_.risk_aversion;

    Eigen::VectorXd net_alpha = alpha_vec - cost_vec;
    Eigen::VectorXd w_prev = w;

    int iter = 0;
    for (iter = 0; iter < max_iter; ++iter) {
        // Compute gradient of the objective w.r.t. w
        // grad = (alpha - cost) - 2 * lambda * Sigma * w
        Eigen::VectorXd grad = net_alpha;
        if (has_cov) {
            grad -= 2.0 * lambda * covariance * w;
        } else {
            // Without covariance, penalise squared weights (diagonal identity)
            grad -= 2.0 * lambda * w;
        }

        // Blend toward alpha-weighted direction: w_i proportional to alpha_i/sigma_i
        // This steers the solution from pure risk-parity toward alpha-informed weights
        Eigen::VectorXd alpha_target(k);
        double alpha_target_sum = 0.0;
        for (int i = 0; i < k; ++i) {
            alpha_target(i) = std::max(0.0, net_alpha(i)) * inv_sigma(i);
            alpha_target_sum += alpha_target(i);
        }
        if (alpha_target_sum > 0.0) {
            alpha_target *= target_sum / alpha_target_sum;
        }

        // Gradient step with momentum toward alpha-weighted target
        double blend = std::min(1.0, static_cast<double>(iter + 1) / 50.0);
        w = w + step_size * grad + 0.005 * blend * (alpha_target - w);

        // -----------------------------------------------------------------
        // Project onto constraint set (clamp and renormalise)
        // -----------------------------------------------------------------

        // (a) Non-negativity (long-only)
        for (int i = 0; i < k; ++i) {
            w(i) = std::max(0.0, w(i));
        }

        // (b) Single-stock cap
        for (int i = 0; i < k; ++i) {
            w(i) = std::min(w(i), constraints_.max_single_weight);
        }

        // (c) Industry cap
        std::unordered_map<int, double> industry_weights;
        for (int i = 0; i < k; ++i) {
            industry_weights[static_cast<int>(industries[i])] += w(i);
        }
        for (const auto& [ind, iw] : industry_weights) {
            if (iw > constraints_.max_industry_weight && iw > 0.0) {
                double scale = constraints_.max_industry_weight / iw;
                for (int i = 0; i < k; ++i) {
                    if (static_cast<int>(industries[i]) == ind) {
                        w(i) *= scale;
                    }
                }
            }
        }

        // (d) Top-3 concentration constraint
        if (k >= 3) {
            std::vector<int> idx(k);
            std::iota(idx.begin(), idx.end(), 0);
            std::partial_sort(idx.begin(), idx.begin() + 3, idx.end(),
                              [&w](int a, int b) { return w(a) > w(b); });
            double top3 = w(idx[0]) + w(idx[1]) + w(idx[2]);
            if (top3 > constraints_.max_top3_weight && top3 > 0.0) {
                double scale = constraints_.max_top3_weight / top3;
                for (int j = 0; j < 3; ++j) {
                    w(idx[j]) *= scale;
                }
            }
        }

        // (e) Max positions: zero out smallest weights if too many
        int num_active = 0;
        for (int i = 0; i < k; ++i) {
            if (w(i) > 0.001) num_active++;
        }
        if (num_active > constraints_.max_positions) {
            std::vector<int> idx(k);
            std::iota(idx.begin(), idx.end(), 0);
            std::sort(idx.begin(), idx.end(),
                      [&w](int a, int b) { return w(a) < w(b); });
            int to_remove = num_active - constraints_.max_positions;
            for (int j = 0; j < k && to_remove > 0; ++j) {
                if (w(idx[j]) > 0.001) {
                    w(idx[j]) = 0.0;
                    to_remove--;
                }
            }
        }

        // (f) Turnover cap: limit deviation from current weights
        double current_turnover = 0.0;
        for (int i = 0; i < k; ++i) {
            current_turnover += std::abs(w(i) - current_w(i));
        }
        if (current_turnover > constraints_.max_turnover && current_turnover > 0.0) {
            double t_scale = constraints_.max_turnover / current_turnover;
            for (int i = 0; i < k; ++i) {
                w(i) = current_w(i) + t_scale * (w(i) - current_w(i));
                w(i) = std::max(0.0, w(i));
            }
        }

        // (g) Beta bounds: tilt weights toward/away from high-beta stocks
        double port_beta = w.dot(betas);
        if (port_beta < constraints_.beta_min && w.sum() > 0.0) {
            // Need more beta: scale up high-beta stocks, scale down low-beta
            for (int j = 0; j < 10; ++j) {
                port_beta = w.dot(betas);
                if (port_beta >= constraints_.beta_min) break;
                for (int i = 0; i < k; ++i) {
                    if (betas(i) > 1.0) w(i) *= 1.02;
                    else if (betas(i) < 1.0 && w(i) > 0.001) w(i) *= 0.98;
                }
            }
        } else if (port_beta > constraints_.beta_max && w.sum() > 0.0) {
            for (int j = 0; j < 10; ++j) {
                port_beta = w.dot(betas);
                if (port_beta <= constraints_.beta_max) break;
                for (int i = 0; i < k; ++i) {
                    if (betas(i) > 1.0 && w(i) > 0.001) w(i) *= 0.98;
                    else if (betas(i) < 1.0) w(i) *= 1.02;
                }
            }
        }

        // (h) Style factor exposure: |z_k| <= max_factor_z per factor
        if (factor_loadings.rows() == k && factor_loadings.cols() > 0) {
            int n_factors = static_cast<int>(factor_loadings.cols());
            Eigen::VectorXd exposures = factor_loadings.transpose() * w;
            for (int f = 0; f < n_factors; ++f) {
                if (std::abs(exposures(f)) > constraints_.max_factor_z) {
                    double sign = (exposures(f) > 0) ? 1.0 : -1.0;
                    double excess = std::abs(exposures(f)) - constraints_.max_factor_z;
                    for (int i = 0; i < k; ++i) {
                        double load = factor_loadings(i, f);
                        if (sign * load > 0.0 && w(i) > 0.001) {
                            w(i) -= 0.5 * excess * load / (factor_loadings.col(f).squaredNorm() + 1e-12);
                            w(i) = std::max(0.0, w(i));
                        }
                    }
                }
            }
        }

        // (i) Normalise to target sum (respect cash floor)
        sum = w.sum();
        if (sum > target_sum) {
            w *= target_sum / sum;
        }

        // Re-clamp single-stock after renormalisation
        for (int i = 0; i < k; ++i) {
            w(i) = std::min(w(i), constraints_.max_single_weight);
        }

        // Check convergence
        double change = (w - w_prev).norm();
        w_prev = w;

        if (change < tol) {
            iter++;
            break;
        }

        // Adaptive step size: reduce if oscillating
        if (iter > 20) {
            step_size *= 0.999;
        }
    }

    result.target_weights = w;

    // -----------------------------------------------------------------------
    // Compute expected metrics
    // -----------------------------------------------------------------------
    result.expected_alpha = result.target_weights.dot(alpha_vec);
    result.expected_cost = result.target_weights.dot(cost_vec);

    if (has_cov) {
        double port_var = result.target_weights.transpose() * covariance * result.target_weights;
        result.expected_risk = std::sqrt(port_var * 252.0);  // annualised
    }

    // -----------------------------------------------------------------------
    // Risk metrics
    // -----------------------------------------------------------------------
    result.risk_metrics.portfolio_beta = result.target_weights.dot(betas);
    result.risk_metrics.gross_exposure = result.target_weights.sum();
    result.risk_metrics.net_exposure = result.target_weights.sum();
    result.risk_metrics.cash_weight = 1.0 - result.target_weights.sum();
    result.risk_metrics.num_positions = 0;
    double max_w = 0.0;
    for (int i = 0; i < k; ++i) {
        if (result.target_weights(i) > 0.001) result.risk_metrics.num_positions++;
        max_w = std::max(max_w, result.target_weights(i));
    }
    result.risk_metrics.max_single_weight = max_w;

    // Top-3 weight
    if (k >= 3) {
        std::vector<double> ws(k);
        for (int i = 0; i < k; ++i) ws[i] = result.target_weights(i);
        std::partial_sort(ws.begin(), ws.begin() + 3, ws.end(), std::greater<double>());
        result.risk_metrics.top3_weight = ws[0] + ws[1] + ws[2];
    } else {
        result.risk_metrics.top3_weight = result.target_weights.sum();
    }

    // Max industry weight
    std::unordered_map<int, double> final_ind_weights;
    for (int i = 0; i < k; ++i) {
        final_ind_weights[static_cast<int>(industries[i])] += result.target_weights(i);
    }
    double max_ind_w = 0.0;
    for (const auto& [ind, iw] : final_ind_weights) {
        max_ind_w = std::max(max_ind_w, iw);
    }
    result.risk_metrics.max_industry_weight = max_ind_w;

    // Turnover
    double turnover = 0.0;
    for (int i = 0; i < k; ++i) {
        turnover += std::abs(result.target_weights(i) - current_w(i));
    }
    result.risk_metrics.turnover = turnover;

    // Check constraints
    result.constraint_violations = check_constraints(
        result.target_weights, betas, industries, covariance, factor_loadings, turnover);

    result.converged = (iter < max_iter);
    result.iterations = iter;
    result.objective_value = result.expected_alpha - result.expected_cost
                            - constraints_.risk_aversion * (result.expected_risk * result.expected_risk);

    return result;
}

std::vector<std::string> PortfolioOptimizer::check_constraints(
    const Eigen::VectorXd& weights,
    const Eigen::VectorXd& betas,
    const std::vector<SWIndustry>& industries,
    const Eigen::MatrixXd& /*covariance*/,
    const Eigen::MatrixXd& /*factor_loadings*/,
    double turnover) const {

    std::vector<std::string> violations;
    int k = static_cast<int>(weights.size());

    // Beta bounds
    double port_beta = weights.dot(betas);
    if (port_beta < constraints_.beta_min)
        violations.push_back("portfolio beta below minimum");
    if (port_beta > constraints_.beta_max)
        violations.push_back("portfolio beta above maximum");

    // Single-stock cap
    for (int i = 0; i < k; ++i) {
        if (weights(i) > constraints_.max_single_weight + 1e-6) {
            violations.push_back("single-stock weight exceeded");
            break;
        }
    }

    // Cash floor
    double cash = 1.0 - weights.sum();
    if (cash < constraints_.cash_floor - 1e-6) {
        violations.push_back("cash below floor");
    }

    // Turnover cap
    if (turnover > constraints_.max_turnover + 1e-6) {
        violations.push_back("turnover exceeded");
    }

    // Number of positions
    int num_pos = 0;
    for (int i = 0; i < k; ++i) {
        if (weights(i) > 0.001) num_pos++;
    }
    if (num_pos > constraints_.max_positions) {
        violations.push_back("too many positions");
    }

    // Industry concentration
    std::unordered_map<int, double> industry_weights;
    for (int i = 0; i < k; ++i) {
        industry_weights[static_cast<int>(industries[i])] += weights(i);
    }
    for (const auto& [ind, w] : industry_weights) {
        if (w > constraints_.max_industry_weight + 1e-6) {
            violations.push_back("industry weight exceeded");
            break;
        }
    }

    return violations;
}

} // namespace trade
