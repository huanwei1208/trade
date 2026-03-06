#pragma once

#include "trade/common/types.h"
#include "trade/model/instrument.h"

#include <Eigen/Dense>
#include <chrono>
#include <string>
#include <unordered_map>
#include <vector>

namespace trade {

// ============================================================================
// RiskMonitor: daily risk monitoring dashboard
// ============================================================================
//
// Tracks four categories of risk metrics on a daily basis:
//
// 1. Ex-ante: VaR, CVaR, target-vol gap, Beta, concentration, factor exposure
// 2. Ex-post: actual vol, drawdown, win rate, turnover, slippage
// 3. Liquidity: liquidation days, ADV participation, lock/suspension weight
// 4. Tail: stress test loss, contribution decomposition
//
// Alert levels:
//   Green  : all metrics within normal bounds
//   Yellow : VaR > 2%, DD > 5%, industry > 28%
//   Orange : VaR > 2.5%, DD > 8%, liquidation days > 2.5
//   Red    : VaR > 3%, DD > 12%, lock+suspended > 15% NAV
//
class RiskMonitor {
public:
    // -----------------------------------------------------------------------
    // Ex-ante risk metrics
    // -----------------------------------------------------------------------
    struct ExAnteMetrics {
        double var_1d_99 = 0.0;             // 1-day 99% VaR as % NAV
        double cvar_1d_99 = 0.0;            // 1-day 99% CVaR
        double target_vol = 0.0;            // target annualised vol
        double ex_ante_vol = 0.0;           // predicted annualised vol
        double vol_gap = 0.0;               // |ex_ante - target| / target
        double portfolio_beta = 0.0;
        double hhi_concentration = 0.0;     // Herfindahl-Hirschman index
        double effective_n = 0.0;           // 1 / HHI

        // Factor exposures: factor name -> z-score
        std::unordered_map<std::string, double> factor_exposures;
        double max_factor_exposure = 0.0;   // max |z|
    };

    // -----------------------------------------------------------------------
    // Ex-post risk metrics
    // -----------------------------------------------------------------------
    struct ExPostMetrics {
        double realized_vol_20d = 0.0;      // 20d annualised vol
        double realized_vol_60d = 0.0;      // 60d annualised vol
        double current_drawdown = 0.0;      // peak-to-trough
        double max_drawdown = 0.0;          // all-time max drawdown
        double win_rate_20d = 0.0;          // fraction of positive days (20d)
        double daily_turnover = 0.0;        // single-side turnover
        double avg_turnover_20d = 0.0;      // 20d average turnover
        double avg_slippage_bps = 0.0;      // average execution slippage
        double tracking_error = 0.0;        // vs benchmark
    };

    // -----------------------------------------------------------------------
    // Liquidity metrics
    // -----------------------------------------------------------------------
    struct LiquidityMetrics {
        double liquidation_days = 0.0;      // max days to unwind
        double avg_adv_participation = 0.0; // avg(|position| / ADV)
        double max_adv_participation = 0.0; // worst-case
        double locked_weight = 0.0;         // weight in limit-down locked stocks
        double suspended_weight = 0.0;      // weight in suspended stocks
        double combined_illiquid_weight = 0.0; // locked + suspended
        int locked_count = 0;
        int suspended_count = 0;
    };

    // -----------------------------------------------------------------------
    // Tail risk metrics
    // -----------------------------------------------------------------------
    struct TailMetrics {
        double stress_test_worst_loss = 0.0;
        std::string stress_test_worst_scenario;
        double stress_var_99 = 0.0;

        // Top risk contributors with marginal / component VaR
        struct RiskContributor {
            Symbol symbol;
            double weight = 0.0;
            double marginal_var = 0.0;
            double component_var = 0.0;
            double stress_loss = 0.0;
        };
        std::vector<RiskContributor> top_contributors;
    };

    // -----------------------------------------------------------------------
    // Alert thresholds
    // -----------------------------------------------------------------------
    struct AlertThresholds {
        // Yellow
        double yellow_var = 0.02;           // VaR > 2%
        double yellow_drawdown = 0.05;      // DD > 5%
        double yellow_industry = 0.28;      // industry > 28%

        // Orange
        double orange_var = 0.025;          // VaR > 2.5%
        double orange_drawdown = 0.08;      // DD > 8%
        double orange_liq_days = 2.5;       // liquidation days > 2.5

        // Red
        double red_var = 0.03;              // VaR > 3%
        double red_drawdown = 0.12;         // DD > 12%
        double red_illiquid_weight = 0.15;  // lock+suspended > 15% NAV
    };

    // -----------------------------------------------------------------------
    // Per-metric alert
    // -----------------------------------------------------------------------
    struct Alert {
        std::string metric_name;
        AlertLevel level = AlertLevel::kGreen;
        double current_value = 0.0;
        double threshold = 0.0;
        std::string message;
    };

    // -----------------------------------------------------------------------
    // Complete risk dashboard
    // -----------------------------------------------------------------------
    struct RiskDashboard {
        Date date;
        ExAnteMetrics ex_ante;
        ExPostMetrics ex_post;
        LiquidityMetrics liquidity;
        TailMetrics tail;

        // Overall alert level (worst across all alerts)
        AlertLevel overall_level = AlertLevel::kGreen;
        std::vector<Alert> alerts;

        // Portfolio summary
        double nav = 0.0;
        double cash_weight = 0.0;
        int num_positions = 0;
        double gross_exposure = 0.0;
        double net_exposure = 0.0;

        // Industry weights: industry -> weight
        std::unordered_map<SWIndustry, double> industry_weights;
        double max_industry_weight = 0.0;
        SWIndustry max_industry = SWIndustry::kUnknown;
    };

    // -----------------------------------------------------------------------
    // Configuration
    // -----------------------------------------------------------------------
    struct Config {
        AlertThresholds thresholds;
        int top_n_contributors = 5;
        double target_vol = 0.15;
    };

    RiskMonitor() : config_{} {}
    explicit RiskMonitor(Config cfg) : config_(cfg) {}

    // -----------------------------------------------------------------------
    // Core interface
    // -----------------------------------------------------------------------

    // Build a complete risk dashboard for the current date.
    //   weights:          (N,) portfolio weights
    //   cov:              (N x N) covariance matrix
    //   returns_matrix:   (T x N) historical returns
    //   nav_series:       historical NAV values
    //   instruments:      instrument metadata
    //   adv:              (N,) 20-day ADV in notional
    //   factor_loadings:  (N x K) factor loading matrix
    //   factor_names:     (K,) factor names
    //   symbols:          (N,) symbol list
    //   date:             the date for this snapshot
    RiskDashboard build_dashboard(
        const Eigen::VectorXd& weights,
        const Eigen::MatrixXd& cov,
        const Eigen::MatrixXd& returns_matrix,
        const std::vector<double>& nav_series,
        const std::unordered_map<Symbol, Instrument>& instruments,
        const Eigen::VectorXd& adv,
        const Eigen::MatrixXd& factor_loadings,
        const std::vector<std::string>& factor_names,
        const std::vector<Symbol>& symbols,
        Date date) const;

    // -----------------------------------------------------------------------
    // Sub-component builders
    // -----------------------------------------------------------------------

    ExAnteMetrics compute_ex_ante(
        const Eigen::VectorXd& weights,
        const Eigen::MatrixXd& cov,
        const Eigen::MatrixXd& factor_loadings,
        const std::vector<std::string>& factor_names,
        const Eigen::VectorXd& betas) const;

    ExPostMetrics compute_ex_post(
        const std::vector<double>& nav_series,
        const std::vector<double>& daily_returns,
        const std::vector<double>& daily_turnovers,
        const std::vector<double>& daily_slippages) const;

    LiquidityMetrics compute_liquidity(
        const Eigen::VectorXd& weights,
        const Eigen::VectorXd& adv,
        const std::vector<Symbol>& symbols,
        const std::unordered_map<Symbol, Instrument>& instruments) const;

    // -----------------------------------------------------------------------
    // Alert generation
    // -----------------------------------------------------------------------

    // Evaluate all alert conditions and return triggered alerts.
    std::vector<Alert> evaluate_alerts(
        const ExAnteMetrics& ex_ante,
        const ExPostMetrics& ex_post,
        const LiquidityMetrics& liquidity,
        const std::unordered_map<SWIndustry, double>& industry_weights) const;

    // Determine the overall alert level from a list of alerts.
    static AlertLevel worst_alert(const std::vector<Alert>& alerts);

    const Config& config() const { return config_; }
    void set_config(const Config& c) { config_ = c; }

private:
    Config config_;
};

} // namespace trade
