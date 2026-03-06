#pragma once

#include "trade/backtest/backtest_engine.h"
#include "trade/backtest/performance.h"
#include "trade/backtest/validation.h"
#include "trade/common/types.h"

#include <Eigen/Dense>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace trade {

// ============================================================================
// Trade detail for reporting
// ============================================================================

struct TradeDetail {
    Symbol symbol;
    Side side = Side::kBuy;
    Date entry_date;
    Date exit_date;
    double entry_price = 0.0;
    double exit_price = 0.0;
    Volume quantity = 0;
    double pnl = 0.0;                    // Realised P&L
    double return_pct = 0.0;             // Return percentage
    double holding_days = 0.0;           // Trading days held
    double commission = 0.0;             // Total commission (entry + exit)
    double slippage_cost = 0.0;          // Total slippage cost
    std::string entry_reason;             // Signal that triggered entry
    std::string exit_reason;              // Reason for exit (signal, stop, rebalance)
};

// ============================================================================
// Performance attribution: decompose returns into sources
// ============================================================================

struct DailyAttribution {
    Date date;
    double total_return = 0.0;           // Gross portfolio return
    double market_return = 0.0;          // Benchmark return (beta * market)
    double alpha_return = 0.0;           // Residual alpha
    double cost_return = 0.0;            // Transaction cost drag (negative)
    double timing_return = 0.0;          // Cash timing contribution
};

struct AttributionSummary {
    double total_return = 0.0;
    double market_contribution = 0.0;    // Cumulative market component
    double alpha_contribution = 0.0;     // Cumulative alpha component
    double cost_drag = 0.0;             // Cumulative cost drag
    double timing_contribution = 0.0;    // Cumulative timing component
    double residual = 0.0;              // Unexplained portion

    // Percentage attribution
    double market_pct() const {
        return total_return != 0.0 ? market_contribution / total_return : 0.0;
    }
    double alpha_pct() const {
        return total_return != 0.0 ? alpha_contribution / total_return : 0.0;
    }
    double cost_pct() const {
        return total_return != 0.0 ? cost_drag / total_return : 0.0;
    }
};

// ============================================================================
// Factor exposure time series
// ============================================================================

struct FactorExposure {
    std::string factor_name;              // e.g., "size", "value", "momentum"
    std::vector<Date> dates;
    std::vector<double> exposures;        // Portfolio factor loading per date
    double avg_exposure = 0.0;
    double std_exposure = 0.0;
    double max_exposure = 0.0;
    double min_exposure = 0.0;
};

// ============================================================================
// Equity curve data point (for charting)
// ============================================================================

struct EquityCurvePoint {
    Date date;
    double strategy_nav = 0.0;           // Strategy NAV (indexed to 1.0)
    double benchmark_nav = 0.0;          // Benchmark NAV (indexed to 1.0)
    double active_nav = 0.0;             // Strategy - Benchmark (cumulative excess)
    double drawdown = 0.0;               // Strategy drawdown from peak
};

// ============================================================================
// BacktestReport: complete report structure for output
// ============================================================================

struct BacktestReport {
    // -----------------------------------------------------------------------
    // Metadata
    // -----------------------------------------------------------------------
    std::string strategy_name;
    std::string strategy_version;
    std::string strategy_params;
    Date start_date;
    Date end_date;
    double initial_capital = 0.0;
    int trading_days = 0;
    std::string benchmark_name;
    std::string generated_at;              // ISO 8601 timestamp

    // -----------------------------------------------------------------------
    // Performance metrics
    // -----------------------------------------------------------------------
    PerformanceReport performance;

    // -----------------------------------------------------------------------
    // Equity curve (for plotting)
    // -----------------------------------------------------------------------
    std::vector<EquityCurvePoint> equity_curve;

    // -----------------------------------------------------------------------
    // Drawdown curve (for plotting)
    // -----------------------------------------------------------------------
    std::vector<std::pair<Date, double>> drawdown_curve;

    // -----------------------------------------------------------------------
    // Monthly return heatmap data
    // -----------------------------------------------------------------------
    // Already in PerformanceReport::monthly_returns

    // -----------------------------------------------------------------------
    // Factor exposure time series
    // -----------------------------------------------------------------------
    std::vector<FactorExposure> factor_exposures;

    // -----------------------------------------------------------------------
    // Trade details
    // -----------------------------------------------------------------------
    std::vector<TradeDetail> trades;

    // -----------------------------------------------------------------------
    // Performance attribution
    // -----------------------------------------------------------------------
    std::vector<DailyAttribution> daily_attribution;
    AttributionSummary attribution_summary;

    // -----------------------------------------------------------------------
    // Overfitting tests
    // -----------------------------------------------------------------------
    OverfitTestResults overfit_tests;

    // -----------------------------------------------------------------------
    // Validation results (if validation was run)
    // -----------------------------------------------------------------------
    std::optional<ValidationResult> validation;

    // -----------------------------------------------------------------------
    // Position history (daily snapshots of top positions)
    // -----------------------------------------------------------------------
    struct DailyPositionSnapshot {
        Date date;
        std::vector<PositionRecord> top_positions;  // Top N by weight
        int total_positions = 0;
        double concentration_top5 = 0.0;             // Weight of top 5
        double concentration_top10 = 0.0;            // Weight of top 10
    };
    std::vector<DailyPositionSnapshot> position_history;

    // -----------------------------------------------------------------------
    // Cost breakdown
    // -----------------------------------------------------------------------
    struct CostSummary {
        double total_commission = 0.0;
        double total_stamp_tax = 0.0;
        double total_transfer_fee = 0.0;
        double total_slippage = 0.0;
        double total_costs = 0.0;
        double cost_as_annual_return_drag = 0.0;
    };
    CostSummary cost_summary;
};

// ============================================================================
// BacktestReporter: generates BacktestReport from engine results
// ============================================================================

class BacktestReporter {
public:
    struct Config {
        int top_n_positions = 10;          // Number of top positions to track
        bool include_trade_details = true;
        bool include_daily_attribution = true;
        bool include_factor_exposures = true;
        bool include_position_history = true;
        std::string benchmark_name = "CSI300";
    };

    BacktestReporter();
    explicit BacktestReporter(Config config);

    // -----------------------------------------------------------------------
    // Report generation
    // -----------------------------------------------------------------------

    // Generate a full report from backtest results.
    BacktestReport generate(
        const BacktestResult& result,
        const IStrategy& strategy) const;

    // Generate with benchmark comparison.
    BacktestReport generate(
        const BacktestResult& result,
        const IStrategy& strategy,
        const std::vector<double>& benchmark_returns) const;

    // Generate with validation results.
    BacktestReport generate(
        const BacktestResult& result,
        const IStrategy& strategy,
        const std::vector<double>& benchmark_returns,
        const ValidationResult& validation) const;

    // -----------------------------------------------------------------------
    // Output formats
    // -----------------------------------------------------------------------

    // Serialize report to JSON string (for Python visualization).
    static std::string to_json(const BacktestReport& report);

    // Serialize report to a JSON file.
    static void to_json_file(const BacktestReport& report,
                             const std::string& path);

    // Serialize equity curve to CSV (date, strategy_nav, benchmark_nav, drawdown).
    static std::string equity_curve_to_csv(const BacktestReport& report);

    // Serialize trade list to CSV.
    static std::string trades_to_csv(const BacktestReport& report);

    // Serialize monthly returns to CSV (year, jan, feb, ..., dec, annual).
    static std::string monthly_returns_to_csv(const BacktestReport& report);

    // Generate a plain-text summary for console output.
    static std::string to_text_summary(const BacktestReport& report);

    // -----------------------------------------------------------------------
    // Component builders (for custom report assembly)
    // -----------------------------------------------------------------------

    // Build equity curve from daily records and benchmark.
    std::vector<EquityCurvePoint> build_equity_curve(
        const std::vector<DailyRecord>& records,
        const std::vector<double>& benchmark_returns) const;

    // Build trade detail list from daily records.
    std::vector<TradeDetail> build_trade_details(
        const std::vector<DailyRecord>& records) const;

    // Build performance attribution from daily records and benchmark.
    std::vector<DailyAttribution> build_attribution(
        const std::vector<DailyRecord>& records,
        const std::vector<double>& benchmark_returns,
        double beta) const;

    // Summarise daily attribution into cumulative totals.
    AttributionSummary summarise_attribution(
        const std::vector<DailyAttribution>& daily) const;

    // Build daily position snapshots (top N by weight).
    std::vector<BacktestReport::DailyPositionSnapshot> build_position_history(
        const std::vector<DailyRecord>& records) const;

    // Build cost summary from daily records.
    BacktestReport::CostSummary build_cost_summary(
        const std::vector<DailyRecord>& records,
        double initial_capital,
        int trading_days) const;

    const Config& config() const { return config_; }

private:
    Config config_;
};

} // namespace trade
