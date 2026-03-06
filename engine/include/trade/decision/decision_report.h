#pragma once

#include "trade/common/types.h"
#include "trade/decision/signal.h"
#include "trade/decision/portfolio_opt.h"

#include <Eigen/Dense>
#include <nlohmann/json.hpp>
#include <string>
#include <unordered_map>
#include <vector>

namespace trade {

// ============================================================================
// DecisionReporter: structured decision report generation
// ============================================================================
// Produces human-readable and machine-parseable JSON reports at two levels:
//
//   1. Per-position report: detailed rationale and risk for a single holding.
//   2. Portfolio-level report: aggregate risk dashboard and constraint status.
//   3. Full report: combines both into a single document.
//
// All reports are emitted as nlohmann::json objects which can be serialised
// to disk, pushed to a dashboard, or consumed by downstream pipelines.
//
class DecisionReporter {
public:
    // -----------------------------------------------------------------------
    // Per-position risk input
    // -----------------------------------------------------------------------
    struct PositionRisk {
        Symbol symbol;
        double target_weight = 0.0;
        double current_weight = 0.0;
        double risk_contribution = 0.0;     // fraction of portfolio risk
        double marginal_var = 0.0;          // dVaR / dw_i
        double liquidity_days = 0.0;        // days to liquidate at ADV pace
    };

    // -----------------------------------------------------------------------
    // Exit plan specification
    // -----------------------------------------------------------------------
    struct ExitPlan {
        int time_stop_days = 0;              // auto-exit after N days if no signal
        double signal_stop = 0.0;            // exit if alpha falls below this
        double risk_stop_pct = 0.0;          // stop-loss pct from entry
        double take_profit_pct = 0.0;        // take-profit pct from entry
    };

    // -----------------------------------------------------------------------
    // Portfolio-level risk dashboard input
    // -----------------------------------------------------------------------
    struct RiskDashboard {
        // Exposure
        double gross_exposure = 0.0;
        double net_exposure = 0.0;
        double cash_weight = 0.0;

        // Sector breakdown: industry -> weight
        std::unordered_map<std::string, double> sector_breakdown;

        // Style factor exposure: factor_name -> z-score
        std::unordered_map<std::string, double> style_exposure;

        // Expected return and risk
        double ex_ante_return = 0.0;         // expected portfolio return (annualised)
        double var_99_1d = 0.0;              // 1-day 99% VaR
        double cvar_99_1d = 0.0;             // 1-day 99% CVaR (expected shortfall)

        // Stress tests
        double stress_loss_2015_crash = 0.0; // loss under 2015 crash scenario
        double stress_loss_2018_trade_war = 0.0;
        double stress_loss_covid_2020 = 0.0;

        // Top risk contributors: symbol -> risk contribution
        std::vector<std::pair<Symbol, double>> top_risk_contributors;

        // Constraint status
        std::vector<std::string> constraint_violations; // empty if all satisfied

        // Market context
        Regime market_regime = Regime::kBull;
        std::string market_sentiment;        // "偏多", "中性", "偏空"
    };

    // -----------------------------------------------------------------------
    // Portfolio state snapshot (for the full report)
    // -----------------------------------------------------------------------
    struct PortfolioSnapshot {
        Date date;
        double nav = 0.0;
        int num_positions = 0;
        std::vector<Symbol> symbols;
        Eigen::VectorXd weights;
        std::unordered_map<Symbol, Signal> signals;
        std::unordered_map<Symbol, PositionRisk> position_risks;
        std::unordered_map<Symbol, ExitPlan> exit_plans;
    };

    DecisionReporter() = default;

    // -----------------------------------------------------------------------
    // Per-position report
    // -----------------------------------------------------------------------
    // Generate a JSON report for a single position.
    //   signal:    the alpha signal for this position
    //   risk:      per-position risk metrics
    //   exit_plan: exit strategy parameters
    //   action:    "buy", "sell", "hold", "reduce", "increase"
    // Returns: JSON object with full position rationale.
    //
    // Schema:
    //   {
    //     "ticker": "600000.SH",
    //     "action": "buy",
    //     "target_weight": 0.05,
    //     "current_weight": 0.00,
    //     "alpha_score": 0.72,
    //     "confidence": 0.85,
    //     "regime": "bull",
    //     "risk_contribution": 0.04,
    //     "marginal_var": 0.012,
    //     "liquidity_days": 1.2,
    //     "entry_reason": "momentum + value convergence",
    //     "invalidators": ["alpha_decay", "sector_rotation", "macro_shock"],
    //     "exit_plan": {
    //       "time_stop_days": 20,
    //       "signal_stop": 0.3,
    //       "risk_stop_pct": -0.08,
    //       "take_profit_pct": 0.15
    //     },
    //     "sentiment": {
    //       "stock_mood": "偏多",
    //       "neg_shock": false,
    //       "key_news": ""
    //     },
    //     "model_scores": [ ... ]
    //   }
    //
    nlohmann::json generate_position_report(
        const Signal& signal,
        const PositionRisk& risk,
        const ExitPlan& exit_plan,
        const std::string& action,
        const std::string& entry_reason = "",
        const std::vector<std::string>& invalidators = {}) const;

    // -----------------------------------------------------------------------
    // Portfolio-level report
    // -----------------------------------------------------------------------
    // Generate a JSON report for the entire portfolio.
    //   dashboard: aggregate risk metrics and constraint status
    // Returns: JSON object with portfolio-level summary.
    //
    // Schema:
    //   {
    //     "gross_exposure": 0.90,
    //     "net_exposure": 0.85,
    //     "cash": 0.10,
    //     "sector_breakdown": { "banking": 0.12, ... },
    //     "style_exposure": { "size": 0.3, "value": -0.2, ... },
    //     "ex_ante_return": 0.15,
    //     "var_99_1d": 0.023,
    //     "cvar_99_1d": 0.031,
    //     "stress_loss_2015_crash": -0.12,
    //     "top_risk_contributors": [ ["600000.SH", 0.04], ... ],
    //     "constraint_violations": [],
    //     "market_regime": "bull",
    //     "market_sentiment": "偏多"
    //   }
    //
    nlohmann::json generate_portfolio_report(
        const RiskDashboard& dashboard) const;

    // -----------------------------------------------------------------------
    // Full report: combined position-level + portfolio-level
    // -----------------------------------------------------------------------
    // Generate a comprehensive JSON document combining per-position reports
    // and the portfolio-level summary into a single report.
    //   portfolio:  snapshot of the current portfolio state
    //   dashboard:  aggregate risk dashboard
    //   exit_plans: exit plan per symbol
    //   actions:    per-symbol action string ("buy", "sell", "hold", ...)
    //   entry_reasons: per-symbol entry reason string
    //   invalidators:  per-symbol invalidator list
    // Returns: JSON object with both levels.
    //
    // Schema:
    //   {
    //     "report_date": "2025-01-15",
    //     "generated_at": "2025-01-15T15:30:00",
    //     "portfolio_summary": { ... },
    //     "positions": [ { ... }, ... ]
    //   }
    //
    nlohmann::json generate_full_report(
        const PortfolioSnapshot& portfolio,
        const RiskDashboard& dashboard,
        const std::unordered_map<Symbol, std::string>& actions = {},
        const std::unordered_map<Symbol, std::string>& entry_reasons = {},
        const std::unordered_map<Symbol, std::vector<std::string>>& invalidators = {}) const;

    // -----------------------------------------------------------------------
    // Serialisation helpers
    // -----------------------------------------------------------------------

    // Write a JSON report to a file (pretty-printed, UTF-8).
    static void write_to_file(const nlohmann::json& report, const std::string& path);

    // Convert a Regime enum to its string representation.
    static std::string regime_to_string(Regime r);

    // Convert a Side enum to its string representation.
    static std::string side_to_string(Side s);
};

} // namespace trade
