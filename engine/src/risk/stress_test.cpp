#include "trade/risk/stress_test.h"

#include <algorithm>
#include <cmath>
#include <numeric>

namespace trade {

// ---------------------------------------------------------------------------
// Built-in scenario factories
// ---------------------------------------------------------------------------

StressTester::Scenario StressTester::make_2015_crash() {
    Scenario s;
    s.name = "2015_crash";
    s.type = ScenarioType::kHistorical;
    s.description = "June-September 2015 leveraged unwind";
    s.duration_days = 60;
    return s;
}

StressTester::Scenario StressTester::make_2020_covid() {
    Scenario s;
    s.name = "2020_covid";
    s.type = ScenarioType::kHistorical;
    s.description = "February 2020 global risk-off";
    s.duration_days = 20;
    return s;
}

StressTester::Scenario StressTester::make_2024_regulatory() {
    Scenario s;
    s.name = "2024_regulatory";
    s.type = ScenarioType::kHistorical;
    s.description = "2024 quant crackdown, micro-cap crash";
    s.duration_days = 15;
    return s;
}

StressTester::Scenario StressTester::make_northbound_reversal() {
    Scenario s;
    s.name = "northbound_reversal";
    s.type = ScenarioType::kFactorShock;
    s.description = "Northbound flow reversal -2 sigma";
    s.factor_shocks["northbound"] = -2.0;
    s.duration_days = 1;
    return s;
}

StressTester::Scenario StressTester::make_csi300_crash() {
    Scenario s;
    s.name = "csi300_crash";
    s.type = ScenarioType::kFactorShock;
    s.description = "CSI300 single-day drawdown -5%";
    s.factor_shocks["market"] = -5.0;
    s.duration_days = 1;
    return s;
}

StressTester::Scenario StressTester::make_momentum_crash() {
    Scenario s;
    s.name = "momentum_crash";
    s.type = ScenarioType::kFactorShock;
    s.description = "Momentum crash -3 sigma, value rally +2 sigma";
    s.factor_shocks["momentum"] = -3.0;
    s.factor_shocks["value"] = 2.0;
    s.duration_days = 1;
    return s;
}

StressTester::Scenario StressTester::make_liquidity_stress() {
    Scenario s;
    s.name = "liquidity_stress";
    s.type = ScenarioType::kLiquidityStress;
    s.description = "Freeze illiquid quartile, forced exit at 10% ADV";
    s.freeze_illiquid_quartile = true;
    s.freeze_days = 3;
    s.forced_exit_adv_pct = 0.10;
    s.slippage_bps_low = 150.0;
    s.slippage_bps_high = 300.0;
    s.duration_days = 3;
    return s;
}

// ---------------------------------------------------------------------------
// Run a single scenario
// ---------------------------------------------------------------------------
StressTester::ScenarioResult StressTester::run_scenario(
    const Eigen::VectorXd& weights,
    const Scenario& scenario,
    const Eigen::MatrixXd& factor_loadings,
    const Eigen::VectorXd& adv,
    const std::vector<Symbol>& symbols) const {

    ScenarioResult result;
    result.scenario_name = scenario.name;
    result.type = scenario.type;
    result.symbols = symbols;

    int N = static_cast<int>(weights.size());
    if (N == 0) return result;

    result.loss_contribution = Eigen::VectorXd::Zero(N);

    switch (scenario.type) {
        case ScenarioType::kHistorical: {
            // ---- Historical scenario replay ----
            // Apply the provided scenario_returns matrix to the current portfolio
            const auto& sr = scenario.scenario_returns;
            int T = static_cast<int>(sr.rows());
            int cols = static_cast<int>(sr.cols());

            if (T == 0 || cols != N) {
                // No scenario data available; estimate based on duration
                // and a generic crash assumption (-3% per day for the period)
                double daily_shock = -0.03;
                double total = daily_shock * scenario.duration_days;
                result.total_loss_pct = weights.cwiseAbs().sum() * total;
                result.worst_day_loss_pct = weights.cwiseAbs().sum() * daily_shock;
                for (int i = 0; i < N; ++i) {
                    result.loss_contribution(i) = weights(i) * total;
                }
                break;
            }

            // Compute daily portfolio returns under scenario
            double cumul_return = 0.0;
            double worst_day = 0.0;
            Eigen::VectorXd cumul_per_stock = Eigen::VectorXd::Zero(N);

            for (int t = 0; t < T; ++t) {
                double day_return = 0.0;
                for (int i = 0; i < N; ++i) {
                    double stock_return = sr(t, i);
                    day_return += weights(i) * stock_return;
                    cumul_per_stock(i) += weights(i) * stock_return;
                }
                cumul_return += day_return;
                worst_day = std::min(worst_day, day_return);
            }

            result.total_loss_pct = cumul_return;  // negative = loss
            result.worst_day_loss_pct = worst_day;
            result.loss_contribution = cumul_per_stock;

            // Stress VaR: use the worst day as a proxy for 99% VaR
            // (conservative: worst observed day in the stress period)
            result.stress_var_99 = -worst_day;
            break;
        }

        case ScenarioType::kFactorShock: {
            // ---- Factor shock scenario ----
            // Apply factor shocks through factor loadings: r_i = sum_k (B_{ik} * shock_k)
            if (factor_loadings.rows() != N || factor_loadings.cols() == 0) {
                // No factor model: use a simple beta-like mapping
                // Assume "market" shock applies uniformly
                double market_shock = 0.0;
                for (auto& [factor, shock_sigma] : scenario.factor_shocks) {
                    // Convert sigma shocks to return shocks (assume 1% daily vol per sigma)
                    market_shock += shock_sigma * 0.01;
                }
                double port_return = weights.sum() * market_shock;
                result.total_loss_pct = port_return;
                result.worst_day_loss_pct = port_return;
                result.stress_var_99 = -port_return;
                for (int i = 0; i < N; ++i) {
                    result.loss_contribution(i) = weights(i) * market_shock;
                }
                break;
            }

            // Build factor names list from factor_loadings columns
            int K = static_cast<int>(factor_loadings.cols());
            std::vector<std::string> factor_names(K);
            for (int k = 0; k < K; ++k) {
                factor_names[k] = "factor_" + std::to_string(k);
            }

            // Common factor name mapping
            std::vector<std::string> known_names = {
                "market", "size", "value", "momentum", "volatility",
                "quality", "northbound", "liquidity"
            };
            for (int k = 0; k < std::min(K, static_cast<int>(known_names.size())); ++k) {
                factor_names[k] = known_names[k];
            }

            Eigen::VectorXd stock_returns = apply_factor_shocks(
                factor_loadings, scenario.factor_shocks, factor_names);

            // Portfolio return under factor shock
            double port_return = weights.dot(stock_returns);
            result.total_loss_pct = port_return;
            result.worst_day_loss_pct = port_return;  // single-day shock
            result.stress_var_99 = -port_return;

            for (int i = 0; i < N; ++i) {
                result.loss_contribution(i) = weights(i) * stock_returns(i);
            }
            break;
        }

        case ScenarioType::kLiquidityStress: {
            // ---- Liquidity stress ----
            // Freeze the bottom quartile by ADV for freeze_days days
            // Forced exit of remaining positions at limited ADV participation + slippage

            if (adv.size() != N) {
                // No ADV data; estimate generic liquidity hit
                result.total_loss_pct = -0.05;  // assume 5% loss
                result.liquidity_adjusted_loss = -0.05;
                break;
            }

            // Find the illiquid quartile (bottom 25% by ADV)
            std::vector<int> indices(N);
            std::iota(indices.begin(), indices.end(), 0);
            std::sort(indices.begin(), indices.end(),
                      [&adv](int a, int b) { return adv(a) < adv(b); });

            int illiquid_count = static_cast<int>(N * config_.illiquid_quantile);
            std::vector<bool> is_frozen(N, false);
            for (int i = 0; i < illiquid_count; ++i) {
                is_frozen[indices[i]] = true;
            }

            // Compute slippage cost for forced liquidation
            double total_slippage = 0.0;
            int frozen_count = 0;
            double avg_slippage_bps = (scenario.slippage_bps_low +
                                       scenario.slippage_bps_high) / 2.0;

            for (int i = 0; i < N; ++i) {
                double position_abs = std::abs(weights(i));
                if (position_abs < 1e-10) continue;

                if (is_frozen[i]) {
                    frozen_count++;
                    // Frozen: cannot exit for freeze_days, assume market drops 2%/day
                    double freeze_loss = position_abs * 0.02 * scenario.freeze_days;
                    // After freeze, forced exit with high slippage
                    double liq_days = (adv(i) > 0)
                        ? position_abs / (adv(i) * scenario.forced_exit_adv_pct)
                        : scenario.freeze_days;
                    double exit_slippage = position_abs *
                        (scenario.slippage_bps_high / 10000.0) * std::sqrt(liq_days);
                    result.loss_contribution(i) = -(freeze_loss + exit_slippage);
                    total_slippage += freeze_loss + exit_slippage;
                } else {
                    // Not frozen: normal exit with moderate slippage
                    double liq_days = (adv(i) > 0)
                        ? position_abs / (adv(i) * scenario.forced_exit_adv_pct)
                        : 1.0;
                    double exit_slippage = position_abs *
                        (avg_slippage_bps / 10000.0) * std::sqrt(std::max(1.0, liq_days));
                    result.loss_contribution(i) = -exit_slippage;
                    total_slippage += exit_slippage;
                }
            }

            result.total_loss_pct = -total_slippage;
            result.worst_day_loss_pct = -total_slippage / std::max(1, scenario.freeze_days);
            result.slippage_cost = total_slippage;
            result.frozen_positions = frozen_count;
            result.liquidity_adjusted_loss = -total_slippage;
            result.stress_var_99 = total_slippage / std::max(1, scenario.freeze_days);
            break;
        }

        case ScenarioType::kCustom: {
            // Custom scenario: replay returns if provided, otherwise factor shocks
            if (scenario.scenario_returns.rows() > 0 &&
                scenario.scenario_returns.cols() == N) {
                // Treat as historical
                Scenario hist_copy = scenario;
                hist_copy.type = ScenarioType::kHistorical;
                return run_scenario(weights, hist_copy, factor_loadings, adv, symbols);
            }
            if (!scenario.factor_shocks.empty()) {
                Scenario factor_copy = scenario;
                factor_copy.type = ScenarioType::kFactorShock;
                return run_scenario(weights, factor_copy, factor_loadings, adv, symbols);
            }
            break;
        }
    }

    // Compute top contributors
    std::vector<ScenarioResult::Contributor> contributors;
    for (int i = 0; i < N; ++i) {
        ScenarioResult::Contributor c;
        c.symbol = (i < static_cast<int>(symbols.size())) ? symbols[i] : "";
        c.loss_pct = result.loss_contribution(i);
        c.weight = weights(i);
        contributors.push_back(c);
    }

    std::sort(contributors.begin(), contributors.end(),
              [](const ScenarioResult::Contributor& a,
                 const ScenarioResult::Contributor& b) {
                  return std::abs(a.loss_pct) > std::abs(b.loss_pct);
              });

    int top_n = std::min(config_.top_n_contributors,
                         static_cast<int>(contributors.size()));
    result.top_contributors.assign(contributors.begin(),
                                    contributors.begin() + top_n);

    return result;
}

// ---------------------------------------------------------------------------
// Run all built-in scenarios and produce aggregate report
// ---------------------------------------------------------------------------
StressTester::StressReport StressTester::run_all(
    const Eigen::VectorXd& weights,
    const Eigen::MatrixXd& factor_loadings,
    const Eigen::VectorXd& adv,
    const std::vector<Symbol>& symbols,
    const std::vector<Scenario>& additional_scenarios) const {

    StressReport report;

    // Collect all scenarios: built-in + custom + additional
    std::vector<Scenario> all_scenarios = {
        make_2015_crash(),
        make_2020_covid(),
        make_2024_regulatory(),
        make_northbound_reversal(),
        make_csi300_crash(),
        make_momentum_crash(),
        make_liquidity_stress()
    };

    // Add custom scenarios
    for (const auto& s : custom_scenarios_) {
        all_scenarios.push_back(s);
    }

    // Add additional scenarios
    for (const auto& s : additional_scenarios) {
        all_scenarios.push_back(s);
    }

    // Run each scenario
    report.worst_scenario_loss = 0.0;
    report.worst_stress_var_99 = 0.0;
    report.worst_liquidity_3d_loss = 0.0;

    for (const auto& scenario : all_scenarios) {
        ScenarioResult result = run_scenario(weights, scenario,
                                              factor_loadings, adv, symbols);
        // total_loss_pct is negative for losses
        double abs_loss = std::abs(result.total_loss_pct);
        if (abs_loss > report.worst_scenario_loss) {
            report.worst_scenario_loss = abs_loss;
            report.worst_scenario_name = result.scenario_name;
        }

        if (result.stress_var_99 > report.worst_stress_var_99) {
            report.worst_stress_var_99 = result.stress_var_99;
        }

        // Track liquidity stress specifically
        if (result.type == ScenarioType::kLiquidityStress) {
            double liq_loss = std::abs(result.liquidity_adjusted_loss);
            report.worst_liquidity_3d_loss = std::max(report.worst_liquidity_3d_loss,
                                                       liq_loss);
        }

        report.results.push_back(std::move(result));
    }

    // Pass/fail criteria
    report.pass_scenario_loss = (report.worst_scenario_loss <= config_.max_scenario_loss);
    report.pass_stress_var = (report.worst_stress_var_99 <= config_.max_stress_var_99);
    report.pass_liquidity_loss = (report.worst_liquidity_3d_loss <= config_.max_liquidity_3d_loss);
    report.overall_pass = report.pass_scenario_loss &&
                          report.pass_stress_var &&
                          report.pass_liquidity_loss;

    return report;
}

// ---------------------------------------------------------------------------
// Register a custom scenario
// ---------------------------------------------------------------------------
void StressTester::add_scenario(Scenario scenario) {
    custom_scenarios_.push_back(std::move(scenario));
}

// ---------------------------------------------------------------------------
// Liquidity-adjusted loss for forced liquidation
// ---------------------------------------------------------------------------
// Total cost = sum_i |w_i * NAV| * slippage * sqrt(days_to_liquidate_i)
// where days_to_liquidate_i = |w_i * NAV| / (adv_i * adv_pct)
double StressTester::liquidity_adjusted_loss(
    const Eigen::VectorXd& weights,
    const Eigen::VectorXd& adv,
    double nav,
    double adv_pct,
    double slippage_bps) {

    int N = static_cast<int>(weights.size());
    if (N == 0 || adv.size() != N) return 0.0;

    double total_cost = 0.0;
    double slippage_frac = slippage_bps / 10000.0;

    for (int i = 0; i < N; ++i) {
        double position = std::abs(weights(i)) * nav;
        if (position < 1e-10) continue;

        double max_daily_exit = (adv(i) > 0.0) ? adv(i) * adv_pct : position;
        double days_to_liq = position / max_daily_exit;

        // Slippage grows with sqrt of time (market impact model)
        double cost = position * slippage_frac * std::sqrt(std::max(1.0, days_to_liq));
        total_cost += cost;
    }

    // Return as fraction of NAV
    return (nav > 0.0) ? total_cost / nav : 0.0;
}

// ---------------------------------------------------------------------------
// Apply factor shocks to compute per-stock returns
// ---------------------------------------------------------------------------
// r_i = sum_k B_{i,k} * shock_k * factor_vol_k
// where shock_k is in sigma units and factor_vol_k is assumed to be the
// daily factor volatility (approximated as 1% for unspecified factors).
Eigen::VectorXd StressTester::apply_factor_shocks(
    const Eigen::MatrixXd& factor_loadings,
    const std::unordered_map<std::string, double>& shocks,
    const std::vector<std::string>& factor_names) {

    int N = static_cast<int>(factor_loadings.rows());
    int K = static_cast<int>(factor_loadings.cols());

    Eigen::VectorXd stock_returns = Eigen::VectorXd::Zero(N);

    // Build a shock vector matching factor column order
    Eigen::VectorXd shock_vec = Eigen::VectorXd::Zero(K);
    for (int k = 0; k < K; ++k) {
        std::string fname = (k < static_cast<int>(factor_names.size()))
                              ? factor_names[k]
                              : ("factor_" + std::to_string(k));
        auto it = shocks.find(fname);
        if (it != shocks.end()) {
            // Convert from sigma to return units
            // Assume daily factor vol = 1% (0.01) per sigma
            shock_vec(k) = it->second * 0.01;
        }
    }

    // r_i = B_i * shock
    stock_returns = factor_loadings * shock_vec;

    return stock_returns;
}

} // namespace trade
