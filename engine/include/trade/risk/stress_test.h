#pragma once

#include "trade/common/types.h"

#include <Eigen/Dense>
#include <functional>
#include <string>
#include <unordered_map>
#include <vector>

namespace trade {

// ============================================================================
// StressTester: scenario-based stress testing
// ============================================================================
//
// Three categories of stress tests:
//
// A) Historical scenario replay:
//      - 2015 crash (June-September): leveraged unwind, circuit breakers
//      - 2020 February Covid: global risk-off, northbound outflows
//      - 2024 regulatory shock: quant crackdown, micro-cap crash
//
// B) Factor shocks:
//      - Northbound flow reversal: -2 sigma
//      - CSI300 single-day drawdown: -5%
//      - Momentum crash / value rally: momentum -3 sigma, value +2 sigma
//
// C) Liquidity stress:
//      - Lowest-liquidity quartile positions frozen for 3 days
//      - Forced exit at 10% ADV participation + 150-300 bps slippage
//
// Pass/fail criteria:
//      - Worst scenario loss <= 8% NAV
//      - Stress VaR_99      <= 3.5% NAV / day
//      - Liquidity-adjusted 3-day loss <= 12% NAV
//
class StressTester {
public:
    // -----------------------------------------------------------------------
    // Scenario definitions
    // -----------------------------------------------------------------------

    enum class ScenarioType : uint8_t {
        kHistorical = 0,
        kFactorShock = 1,
        kLiquidityStress = 2,
        kCustom = 3,
    };

    struct Scenario {
        std::string name;
        ScenarioType type = ScenarioType::kCustom;
        std::string description;

        // For historical replay: daily return vectors during stress period
        // Each column is an asset, each row is a day in the scenario window
        Eigen::MatrixXd scenario_returns;   // (T_scenario x N)

        // For factor shocks: factor return shocks
        // Key = factor name, Value = shock magnitude in sigma
        std::unordered_map<std::string, double> factor_shocks;

        // For liquidity stress
        bool freeze_illiquid_quartile = false;
        int freeze_days = 3;
        double forced_exit_adv_pct = 0.10;      // 10% ADV participation
        double slippage_bps_low = 150.0;         // 150 bps
        double slippage_bps_high = 300.0;        // 300 bps

        // Duration of the scenario in trading days
        int duration_days = 1;
    };

    // -----------------------------------------------------------------------
    // Per-scenario results
    // -----------------------------------------------------------------------
    struct ScenarioResult {
        std::string scenario_name;
        ScenarioType type;

        double total_loss_pct = 0.0;        // as fraction of NAV (negative = loss)
        double worst_day_loss_pct = 0.0;    // single worst day
        double stress_var_99 = 0.0;         // 99% VaR under stressed distribution

        // Contribution decomposition: loss attributed to each stock
        std::vector<Symbol> symbols;
        Eigen::VectorXd loss_contribution;  // (N,) per-stock loss

        // Top contributors
        struct Contributor {
            Symbol symbol;
            double loss_pct = 0.0;
            double weight = 0.0;
        };
        std::vector<Contributor> top_contributors;  // sorted by |loss|

        // Liquidity-specific
        double liquidity_adjusted_loss = 0.0;
        double slippage_cost = 0.0;
        int frozen_positions = 0;
    };

    // -----------------------------------------------------------------------
    // Aggregate stress test report
    // -----------------------------------------------------------------------
    struct StressReport {
        std::vector<ScenarioResult> results;

        // Worst-case across all scenarios
        double worst_scenario_loss = 0.0;
        std::string worst_scenario_name;
        double worst_stress_var_99 = 0.0;
        double worst_liquidity_3d_loss = 0.0;

        // Pass/fail criteria
        bool pass_scenario_loss = false;    // worst <= 8% NAV
        bool pass_stress_var = false;       // stress VaR_99 <= 3.5% NAV/day
        bool pass_liquidity_loss = false;   // liq-adj 3d loss <= 12% NAV
        bool overall_pass = false;          // all three pass
    };

    // -----------------------------------------------------------------------
    // Configuration
    // -----------------------------------------------------------------------
    struct Config {
        // Pass/fail thresholds
        double max_scenario_loss = 0.08;           // 8% NAV
        double max_stress_var_99 = 0.035;          // 3.5% NAV/day
        double max_liquidity_3d_loss = 0.12;       // 12% NAV

        // Top-N contributors to report
        int top_n_contributors = 5;

        // Liquidity parameters
        double illiquid_quantile = 0.25;  // bottom 25% by ADV
    };

    StressTester() : config_{} {}
    explicit StressTester(Config cfg) : config_(cfg) {}

    // -----------------------------------------------------------------------
    // Built-in scenario factories
    // -----------------------------------------------------------------------

    // Historical scenarios -- return scenario definitions that can be
    // populated with actual market data via set_scenario_returns().
    static Scenario make_2015_crash();          // Jun-Sep 2015
    static Scenario make_2020_covid();          // Feb 2020
    static Scenario make_2024_regulatory();     // 2024 regulatory shock

    // Factor shock scenarios
    static Scenario make_northbound_reversal(); // northbound flow -2 sigma
    static Scenario make_csi300_crash();        // CSI300 single day -5%
    static Scenario make_momentum_crash();      // momentum -3 sigma, value +2 sigma

    // Liquidity stress
    static Scenario make_liquidity_stress();    // freeze illiquid Q1, forced exit

    // -----------------------------------------------------------------------
    // Core interface
    // -----------------------------------------------------------------------

    // Run a single scenario
    //   weights:          (N,) portfolio weights
    //   scenario:         scenario definition
    //   factor_loadings:  (N x K) factor exposures (for factor shock scenarios)
    //   adv:              (N,) 20-day ADV in notional (for liquidity stress)
    //   symbols:          (N,) symbol identifiers
    ScenarioResult run_scenario(
        const Eigen::VectorXd& weights,
        const Scenario& scenario,
        const Eigen::MatrixXd& factor_loadings = {},
        const Eigen::VectorXd& adv = {},
        const std::vector<Symbol>& symbols = {}) const;

    // Run all built-in scenarios and produce aggregate report
    StressReport run_all(
        const Eigen::VectorXd& weights,
        const Eigen::MatrixXd& factor_loadings = {},
        const Eigen::VectorXd& adv = {},
        const std::vector<Symbol>& symbols = {},
        const std::vector<Scenario>& additional_scenarios = {}) const;

    // Register a custom scenario for inclusion in run_all()
    void add_scenario(Scenario scenario);

    // -----------------------------------------------------------------------
    // Utilities
    // -----------------------------------------------------------------------

    // Compute liquidity-adjusted loss for forced liquidation
    //   weights:   (N,) portfolio weights
    //   adv:       (N,) 20-day ADV in notional
    //   nav:       total NAV
    //   adv_pct:   max participation rate (fraction of ADV)
    //   slippage:  slippage in bps per unit of participation
    static double liquidity_adjusted_loss(
        const Eigen::VectorXd& weights,
        const Eigen::VectorXd& adv,
        double nav,
        double adv_pct,
        double slippage_bps);

    const Config& config() const { return config_; }
    const std::vector<Scenario>& custom_scenarios() const { return custom_scenarios_; }

private:
    Config config_;
    std::vector<Scenario> custom_scenarios_;

    // Apply factor shocks to compute per-stock returns
    static Eigen::VectorXd apply_factor_shocks(
        const Eigen::MatrixXd& factor_loadings,
        const std::unordered_map<std::string, double>& shocks,
        const std::vector<std::string>& factor_names);
};

} // namespace trade
