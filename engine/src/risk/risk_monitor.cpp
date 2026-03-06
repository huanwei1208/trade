#include "trade/risk/risk_monitor.h"
#include "trade/model/instrument.h"

#include <algorithm>
#include <cmath>
#include <numeric>

namespace trade {

// ---------------------------------------------------------------------------
// Build complete risk dashboard
// ---------------------------------------------------------------------------
RiskMonitor::RiskDashboard RiskMonitor::build_dashboard(
    const Eigen::VectorXd& weights,
    const Eigen::MatrixXd& cov,
    const Eigen::MatrixXd& returns_matrix,
    const std::vector<double>& nav_series,
    const std::unordered_map<Symbol, Instrument>& instruments,
    const Eigen::VectorXd& adv,
    const Eigen::MatrixXd& factor_loadings,
    const std::vector<std::string>& factor_names,
    const std::vector<Symbol>& symbols,
    Date date) const {

    RiskDashboard dashboard;
    dashboard.date = date;

    int N = static_cast<int>(weights.size());
    if (N == 0) return dashboard;

    // ---- Portfolio summary ----
    dashboard.num_positions = 0;
    dashboard.gross_exposure = 0.0;
    dashboard.net_exposure = 0.0;

    for (int i = 0; i < N; ++i) {
        if (std::abs(weights(i)) > 1e-10) {
            dashboard.num_positions++;
        }
        dashboard.gross_exposure += std::abs(weights(i));
        dashboard.net_exposure += weights(i);
    }

    dashboard.cash_weight = std::max(0.0, 1.0 - dashboard.gross_exposure);
    if (!nav_series.empty()) {
        dashboard.nav = nav_series.back();
    }

    // ---- Industry weights ----
    for (int i = 0; i < N; ++i) {
        SWIndustry ind = SWIndustry::kUnknown;
        if (i < static_cast<int>(symbols.size())) {
            auto it = instruments.find(symbols[i]);
            if (it != instruments.end()) {
                ind = it->second.industry;
            }
        }
        dashboard.industry_weights[ind] += std::abs(weights(i));
    }

    dashboard.max_industry_weight = 0.0;
    dashboard.max_industry = SWIndustry::kUnknown;
    for (auto& [ind, w] : dashboard.industry_weights) {
        if (w > dashboard.max_industry_weight) {
            dashboard.max_industry_weight = w;
            dashboard.max_industry = ind;
        }
    }

    // ---- Construct betas vector from instruments ----
    Eigen::VectorXd betas = Eigen::VectorXd::Ones(N);
    // (No beta field in Instrument; use default 1.0)

    // ---- Ex-ante metrics ----
    dashboard.ex_ante = compute_ex_ante(weights, cov, factor_loadings,
                                         factor_names, betas);

    // ---- Ex-post metrics ----
    // Compute daily portfolio returns from NAV series
    std::vector<double> daily_returns;
    if (nav_series.size() >= 2) {
        daily_returns.reserve(nav_series.size() - 1);
        for (size_t i = 1; i < nav_series.size(); ++i) {
            if (nav_series[i - 1] > 0.0) {
                daily_returns.push_back(
                    (nav_series[i] - nav_series[i - 1]) / nav_series[i - 1]);
            }
        }
    }

    // Placeholder: daily turnover and slippage arrays (not available from inputs)
    std::vector<double> daily_turnovers;
    std::vector<double> daily_slippages;
    dashboard.ex_post = compute_ex_post(nav_series, daily_returns,
                                         daily_turnovers, daily_slippages);

    // ---- Liquidity metrics ----
    dashboard.liquidity = compute_liquidity(weights, adv, symbols, instruments);

    // ---- Tail risk metrics ----
    // Compute VaR contributions for top risk contributors
    if (cov.rows() == N && cov.cols() == N) {
        double port_var_val = (weights.transpose() * cov * weights).value();
        double sigma_p = std::sqrt(std::max(0.0, port_var_val));
        double z99 = 2.326;

        if (sigma_p > 1e-15) {
            Eigen::VectorXd sigma_w = cov * weights;
            Eigen::VectorXd m_var = (sigma_w / sigma_p) * z99;
            Eigen::VectorXd c_var = weights.array() * m_var.array();

            // Build top contributors list
            struct IndexedContrib {
                int idx;
                double abs_cvar;
            };
            std::vector<IndexedContrib> sorted_contribs(N);
            for (int i = 0; i < N; ++i) {
                sorted_contribs[i] = {i, std::abs(c_var(i))};
            }
            std::sort(sorted_contribs.begin(), sorted_contribs.end(),
                      [](const IndexedContrib& a, const IndexedContrib& b) {
                          return a.abs_cvar > b.abs_cvar;
                      });

            int top_n = std::min(config_.top_n_contributors, N);
            for (int k = 0; k < top_n; ++k) {
                int i = sorted_contribs[k].idx;
                TailMetrics::RiskContributor rc;
                rc.symbol = (i < static_cast<int>(symbols.size())) ? symbols[i] : "";
                rc.weight = weights(i);
                rc.marginal_var = m_var(i);
                rc.component_var = c_var(i);
                rc.stress_loss = 0.0;
                dashboard.tail.top_contributors.push_back(rc);
            }
        }

        dashboard.tail.stress_var_99 = dashboard.ex_ante.var_1d_99;
    }

    // ---- Alerts ----
    dashboard.alerts = evaluate_alerts(dashboard.ex_ante, dashboard.ex_post,
                                        dashboard.liquidity,
                                        dashboard.industry_weights);
    dashboard.overall_level = worst_alert(dashboard.alerts);

    return dashboard;
}

// ---------------------------------------------------------------------------
// Ex-ante risk metrics
// ---------------------------------------------------------------------------
RiskMonitor::ExAnteMetrics RiskMonitor::compute_ex_ante(
    const Eigen::VectorXd& weights,
    const Eigen::MatrixXd& cov,
    const Eigen::MatrixXd& factor_loadings,
    const std::vector<std::string>& factor_names,
    const Eigen::VectorXd& betas) const {

    ExAnteMetrics metrics;
    int N = static_cast<int>(weights.size());
    if (N == 0) return metrics;

    // Portfolio variance and vol
    double port_var = 0.0;
    if (cov.rows() == N && cov.cols() == N) {
        port_var = (weights.transpose() * cov * weights).value();
    }
    port_var = std::max(0.0, port_var);
    double sigma_p = std::sqrt(port_var);

    // Annualised ex-ante vol
    metrics.ex_ante_vol = sigma_p * std::sqrt(252.0);
    metrics.target_vol = config_.target_vol;

    // Vol gap: |ex_ante - target| / target
    if (metrics.target_vol > 0.0) {
        metrics.vol_gap = std::abs(metrics.ex_ante_vol - metrics.target_vol)
                          / metrics.target_vol;
    }

    // 1-day 99% VaR / CVaR (parametric)
    double z99 = 2.326;
    metrics.var_1d_99 = z99 * sigma_p;
    // CVaR: phi(z) / (1-alpha) * sigma
    double phi_z = std::exp(-0.5 * z99 * z99) / std::sqrt(2.0 * M_PI);
    metrics.cvar_1d_99 = (phi_z / 0.01) * sigma_p;

    // Portfolio beta
    if (betas.size() == N) {
        metrics.portfolio_beta = weights.dot(betas);
    }

    // HHI concentration: sum(w_i^2)
    metrics.hhi_concentration = weights.squaredNorm();
    metrics.effective_n = (metrics.hhi_concentration > 1e-15)
                            ? 1.0 / metrics.hhi_concentration : 0.0;

    // Factor exposures: portfolio loading on each factor
    if (factor_loadings.rows() == N && factor_loadings.cols() > 0) {
        int K = static_cast<int>(factor_loadings.cols());
        Eigen::VectorXd port_loading = factor_loadings.transpose() * weights;

        metrics.max_factor_exposure = 0.0;
        for (int k = 0; k < K; ++k) {
            std::string fname = (k < static_cast<int>(factor_names.size()))
                                  ? factor_names[k]
                                  : ("factor_" + std::to_string(k));
            double exposure = port_loading(k);
            metrics.factor_exposures[fname] = exposure;
            metrics.max_factor_exposure = std::max(metrics.max_factor_exposure,
                                                    std::abs(exposure));
        }
    }

    return metrics;
}

// ---------------------------------------------------------------------------
// Ex-post risk metrics
// ---------------------------------------------------------------------------
RiskMonitor::ExPostMetrics RiskMonitor::compute_ex_post(
    const std::vector<double>& nav_series,
    const std::vector<double>& daily_returns,
    const std::vector<double>& daily_turnovers,
    const std::vector<double>& daily_slippages) const {

    ExPostMetrics metrics;

    int n_ret = static_cast<int>(daily_returns.size());

    // Realized volatility (20d and 60d)
    auto compute_vol = [](const std::vector<double>& returns, int window) -> double {
        int n = static_cast<int>(returns.size());
        int start = std::max(0, n - window);
        int count = n - start;
        if (count <= 1) return 0.0;

        double sum = 0.0;
        for (int i = start; i < n; ++i) sum += returns[i];
        double mean = sum / count;

        double sum_sq = 0.0;
        for (int i = start; i < n; ++i) {
            double d = returns[i] - mean;
            sum_sq += d * d;
        }
        return std::sqrt(sum_sq / (count - 1) * 252.0);
    };

    metrics.realized_vol_20d = compute_vol(daily_returns, 20);
    metrics.realized_vol_60d = compute_vol(daily_returns, 60);

    // Current drawdown
    if (!nav_series.empty()) {
        double peak = nav_series.front();
        double max_dd = 0.0;
        for (double nav : nav_series) {
            if (nav > peak) peak = nav;
            double dd = (peak - nav) / peak;
            max_dd = std::max(max_dd, dd);
        }
        metrics.max_drawdown = max_dd;

        // Current drawdown: from most recent peak to current value
        peak = nav_series.front();
        for (double nav : nav_series) {
            if (nav > peak) peak = nav;
        }
        double current = nav_series.back();
        metrics.current_drawdown = (peak > 0.0) ? (peak - current) / peak : 0.0;
    }

    // Win rate (20d): fraction of positive days
    if (n_ret > 0) {
        int window = std::min(20, n_ret);
        int start = n_ret - window;
        int wins = 0;
        for (int i = start; i < n_ret; ++i) {
            if (daily_returns[i] > 0.0) wins++;
        }
        metrics.win_rate_20d = static_cast<double>(wins) / window;
    }

    // Turnover
    if (!daily_turnovers.empty()) {
        metrics.daily_turnover = daily_turnovers.back();
        int window = std::min(20, static_cast<int>(daily_turnovers.size()));
        int start = static_cast<int>(daily_turnovers.size()) - window;
        double sum = 0.0;
        for (int i = start; i < static_cast<int>(daily_turnovers.size()); ++i) {
            sum += daily_turnovers[i];
        }
        metrics.avg_turnover_20d = sum / window;
    }

    // Average slippage
    if (!daily_slippages.empty()) {
        double sum = 0.0;
        int window = std::min(20, static_cast<int>(daily_slippages.size()));
        int start = static_cast<int>(daily_slippages.size()) - window;
        for (int i = start; i < static_cast<int>(daily_slippages.size()); ++i) {
            sum += daily_slippages[i];
        }
        metrics.avg_slippage_bps = sum / window;
    }

    // Tracking error: standard deviation of daily returns vs benchmark
    // (without benchmark data, use portfolio vol as a proxy)
    metrics.tracking_error = metrics.realized_vol_20d;

    return metrics;
}

// ---------------------------------------------------------------------------
// Liquidity metrics
// ---------------------------------------------------------------------------
RiskMonitor::LiquidityMetrics RiskMonitor::compute_liquidity(
    const Eigen::VectorXd& weights,
    const Eigen::VectorXd& adv,
    const std::vector<Symbol>& symbols,
    const std::unordered_map<Symbol, Instrument>& instruments) const {

    LiquidityMetrics metrics;
    int N = static_cast<int>(weights.size());
    if (N == 0) return metrics;

    // Compute ADV participation and liquidation days
    double max_liq_days = 0.0;
    double sum_participation = 0.0;
    double max_participation = 0.0;
    int active_count = 0;

    for (int i = 0; i < N; ++i) {
        double abs_w = std::abs(weights(i));
        if (abs_w < 1e-10) continue;
        active_count++;

        if (adv.size() == N && adv(i) > 0.0) {
            // Participation: position / ADV (as fraction)
            double participation = abs_w / adv(i);
            sum_participation += participation;
            max_participation = std::max(max_participation, participation);

            // Liquidation days: position_notional / ADV
            // weights are fraction of NAV, so position = w * NAV ~ w for NAV=1
            double liq_days = abs_w / adv(i);
            max_liq_days = std::max(max_liq_days, liq_days);
        }
    }

    metrics.liquidation_days = max_liq_days;
    metrics.max_adv_participation = max_participation;
    metrics.avg_adv_participation = (active_count > 0)
                                      ? sum_participation / active_count : 0.0;

    // Locked and suspended weight
    for (int i = 0; i < N; ++i) {
        if (i >= static_cast<int>(symbols.size())) continue;
        auto it = instruments.find(symbols[i]);
        if (it == instruments.end()) continue;

        const auto& inst = it->second;
        double abs_w = std::abs(weights(i));

        if (inst.status == TradingStatus::kSuspended) {
            metrics.suspended_weight += abs_w;
            metrics.suspended_count++;
        }
        // Limit-down detection would require intraday data;
        // here we check for ST status as a proxy for lock risk
        if (inst.status == TradingStatus::kST ||
            inst.status == TradingStatus::kStarST) {
            metrics.locked_weight += abs_w;
            metrics.locked_count++;
        }
    }

    metrics.combined_illiquid_weight = metrics.locked_weight + metrics.suspended_weight;

    return metrics;
}

// ---------------------------------------------------------------------------
// Alert evaluation
// ---------------------------------------------------------------------------
std::vector<RiskMonitor::Alert> RiskMonitor::evaluate_alerts(
    const ExAnteMetrics& ex_ante,
    const ExPostMetrics& ex_post,
    const LiquidityMetrics& liquidity,
    const std::unordered_map<SWIndustry, double>& industry_weights) const {

    std::vector<Alert> alerts;
    const auto& t = config_.thresholds;

    // Helper: add alert if value exceeds threshold
    auto check = [&](const std::string& name, double value,
                     double yellow_thresh, double orange_thresh,
                     double red_thresh, const std::string& unit) {
        if (value > red_thresh) {
            Alert a;
            a.metric_name = name;
            a.level = AlertLevel::kRed;
            a.current_value = value;
            a.threshold = red_thresh;
            a.message = name + " = " + std::to_string(value) + unit +
                        " exceeds red threshold " + std::to_string(red_thresh) + unit;
            alerts.push_back(a);
        } else if (value > orange_thresh) {
            Alert a;
            a.metric_name = name;
            a.level = AlertLevel::kOrange;
            a.current_value = value;
            a.threshold = orange_thresh;
            a.message = name + " = " + std::to_string(value) + unit +
                        " exceeds orange threshold " + std::to_string(orange_thresh) + unit;
            alerts.push_back(a);
        } else if (value > yellow_thresh) {
            Alert a;
            a.metric_name = name;
            a.level = AlertLevel::kYellow;
            a.current_value = value;
            a.threshold = yellow_thresh;
            a.message = name + " = " + std::to_string(value) + unit +
                        " exceeds yellow threshold " + std::to_string(yellow_thresh) + unit;
            alerts.push_back(a);
        }
    };

    // VaR alerts
    check("VaR_1d_99", ex_ante.var_1d_99,
          t.yellow_var, t.orange_var, t.red_var, "");

    // Drawdown alerts
    check("Drawdown", ex_post.current_drawdown,
          t.yellow_drawdown, t.orange_drawdown, t.red_drawdown, "");

    // Industry concentration
    double max_ind = 0.0;
    for (auto& [ind, w] : industry_weights) {
        max_ind = std::max(max_ind, w);
    }
    check("MaxIndustry", max_ind,
          t.yellow_industry, 1.0, 1.0, "");  // only yellow for industry

    // Liquidation days (orange threshold only)
    if (liquidity.liquidation_days > t.orange_liq_days) {
        Alert a;
        a.metric_name = "LiquidationDays";
        a.level = AlertLevel::kOrange;
        a.current_value = liquidity.liquidation_days;
        a.threshold = t.orange_liq_days;
        a.message = "Liquidation days = " +
                    std::to_string(liquidity.liquidation_days) +
                    " exceeds orange threshold " +
                    std::to_string(t.orange_liq_days);
        alerts.push_back(a);
    }

    // Illiquid weight (red threshold only)
    if (liquidity.combined_illiquid_weight > t.red_illiquid_weight) {
        Alert a;
        a.metric_name = "IlliquidWeight";
        a.level = AlertLevel::kRed;
        a.current_value = liquidity.combined_illiquid_weight;
        a.threshold = t.red_illiquid_weight;
        a.message = "Combined illiquid weight = " +
                    std::to_string(liquidity.combined_illiquid_weight) +
                    " exceeds red threshold " +
                    std::to_string(t.red_illiquid_weight);
        alerts.push_back(a);
    }

    return alerts;
}

// ---------------------------------------------------------------------------
// Worst alert level
// ---------------------------------------------------------------------------
AlertLevel RiskMonitor::worst_alert(const std::vector<Alert>& alerts) {
    AlertLevel worst = AlertLevel::kGreen;
    for (const auto& a : alerts) {
        if (a.level > worst) worst = a.level;
    }
    return worst;
}

} // namespace trade
