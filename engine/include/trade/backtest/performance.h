#pragma once

#include "trade/backtest/backtest_engine.h"
#include "trade/common/types.h"

#include <Eigen/Dense>
#include <array>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace trade {

// ============================================================================
// PerformanceReport: comprehensive backtest performance metrics
// ============================================================================

struct PerformanceReport {
    // -----------------------------------------------------------------------
    // Return metrics
    // -----------------------------------------------------------------------
    double annualised_return = 0.0;       // Geometric annualised return
    double cumulative_return = 0.0;       // Total return over period
    double cagr = 0.0;                    // Compound annual growth rate

    // Monthly return heatmap: monthly_returns[year][month-1]
    // Keyed by year (e.g., 2020), array of 12 monthly returns.
    std::unordered_map<int, std::array<double, 12>> monthly_returns;

    // -----------------------------------------------------------------------
    // Risk-adjusted metrics
    // -----------------------------------------------------------------------
    double sharpe_ratio = 0.0;            // Annualised Sharpe (rf = 0 or configurable)
    double sortino_ratio = 0.0;           // Downside deviation denominator
    double calmar_ratio = 0.0;            // Ann. return / max drawdown
    double information_ratio = 0.0;       // Active return / tracking error

    // -----------------------------------------------------------------------
    // Drawdown metrics
    // -----------------------------------------------------------------------
    double max_drawdown = 0.0;            // Maximum peak-to-trough drawdown
    int max_drawdown_duration = 0;        // Trading days in longest drawdown
    double avg_drawdown = 0.0;            // Average drawdown depth
    Date max_drawdown_start;              // Start date of max drawdown period
    Date max_drawdown_end;                // End date (trough) of max drawdown
    Date max_drawdown_recovery;           // Recovery date (if recovered)

    // -----------------------------------------------------------------------
    // Trading metrics
    // -----------------------------------------------------------------------
    double win_rate = 0.0;                // Fraction of trades with positive P&L
    double profit_loss_ratio = 0.0;       // Avg win / avg loss (absolute)
    double profit_factor = 0.0;           // Gross profit / gross loss
    double avg_holding_days = 0.0;        // Average holding period in trading days
    int total_trades = 0;                 // Total number of round-trip trades
    int winning_trades = 0;
    int losing_trades = 0;
    double avg_trade_pnl = 0.0;           // Average P&L per round-trip trade
    double largest_win = 0.0;
    double largest_loss = 0.0;

    // -----------------------------------------------------------------------
    // Turnover and cost metrics
    // -----------------------------------------------------------------------
    double avg_daily_turnover = 0.0;      // Average daily turnover as NAV fraction
    double total_turnover = 0.0;          // Sum of daily turnovers
    double total_trades_count = 0;        // Total individual order fills
    double avg_cost_per_trade = 0.0;      // Average transaction cost per fill
    double total_costs = 0.0;             // Total transaction costs
    double cost_drag = 0.0;              // Annualised cost as return drag

    // -----------------------------------------------------------------------
    // Benchmark-relative metrics (vs CSI300/CSI500)
    // -----------------------------------------------------------------------
    double alpha = 0.0;                   // Jensen's alpha (annualised)
    double beta = 0.0;                    // Market beta
    double tracking_error = 0.0;          // Annualised tracking error
    double active_return = 0.0;           // Annualised return - benchmark return
    double benchmark_return = 0.0;        // Annualised benchmark return
    double benchmark_sharpe = 0.0;        // Benchmark Sharpe for comparison
    double correlation = 0.0;             // Correlation with benchmark
    double r_squared = 0.0;              // R^2 from CAPM regression

    // -----------------------------------------------------------------------
    // Statistical confidence metrics
    // -----------------------------------------------------------------------
    double sharpe_bootstrap_ci_lower = 0.0;   // 95% CI lower bound (bootstrap)
    double sharpe_bootstrap_ci_upper = 0.0;   // 95% CI upper bound
    double deflated_sharpe_ratio = 0.0;       // DSR (Bailey & Lopez de Prado)
    double sharpe_t_statistic = 0.0;          // t-stat for Sharpe > 0
    double sharpe_p_value = 0.0;              // p-value for Sharpe > 0

    // -----------------------------------------------------------------------
    // VaR / Tail risk
    // -----------------------------------------------------------------------
    double var_95 = 0.0;                  // Historical VaR at 95% (daily)
    double var_99 = 0.0;                  // Historical VaR at 99% (daily)
    double cvar_95 = 0.0;                 // Conditional VaR (Expected Shortfall) 95%
    double skewness = 0.0;               // Return distribution skewness
    double kurtosis = 0.0;               // Return distribution excess kurtosis

    // -----------------------------------------------------------------------
    // Exposure metrics
    // -----------------------------------------------------------------------
    double avg_num_positions = 0.0;
    double avg_gross_exposure = 0.0;
    double avg_cash_weight = 0.0;
};

// ============================================================================
// PerformanceCalculator: compute all metrics from backtest results
// ============================================================================

class PerformanceCalculator {
public:
    struct Config {
        double risk_free_rate = 0.025;        // Annual risk-free rate (China 10Y)
        int annualisation_factor = 252;       // Trading days per year
        int bootstrap_samples = 10000;        // Number of bootstrap resamples
        int bootstrap_block_size = 21;        // Block size for block bootstrap (1 month)
        std::string benchmark_name = "CSI300"; // Benchmark name for reporting
    };

    PerformanceCalculator();
    explicit PerformanceCalculator(Config config);

    // -----------------------------------------------------------------------
    // Core computation
    // -----------------------------------------------------------------------

    // Compute the full performance report from backtest results.
    PerformanceReport compute(const BacktestResult& result) const;

    // Compute with benchmark comparison.
    PerformanceReport compute(const BacktestResult& result,
                              const std::vector<double>& benchmark_returns) const;

    // -----------------------------------------------------------------------
    // Individual metric groups (for selective computation)
    // -----------------------------------------------------------------------

    // Return metrics
    double annualised_return(const std::vector<double>& daily_returns) const;
    double cumulative_return(const std::vector<double>& daily_returns) const;
    std::unordered_map<int, std::array<double, 12>> monthly_return_heatmap(
        const std::vector<DailyRecord>& records) const;

    // Risk-adjusted metrics
    double sharpe_ratio(const std::vector<double>& daily_returns) const;
    double sortino_ratio(const std::vector<double>& daily_returns) const;
    double calmar_ratio(const std::vector<double>& daily_returns,
                        double max_dd) const;
    double information_ratio(const std::vector<double>& active_returns) const;

    // Drawdown analysis
    struct DrawdownInfo {
        double max_drawdown = 0.0;
        int max_drawdown_duration = 0;     // In trading days
        double avg_drawdown = 0.0;
        int peak_index = 0;
        int trough_index = 0;
        int recovery_index = -1;           // -1 if not recovered
    };
    DrawdownInfo analyse_drawdowns(const std::vector<double>& nav_series) const;

    // Trading statistics
    struct TradeStats {
        double win_rate = 0.0;
        double profit_loss_ratio = 0.0;
        double profit_factor = 0.0;
        double avg_holding_days = 0.0;
        int total_trades = 0;
        int winning_trades = 0;
        int losing_trades = 0;
        double avg_trade_pnl = 0.0;
        double largest_win = 0.0;
        double largest_loss = 0.0;
    };
    TradeStats compute_trade_stats(const std::vector<DailyRecord>& records) const;

    // Benchmark regression (CAPM: r_i = alpha + beta * r_m + eps)
    struct BenchmarkStats {
        double alpha = 0.0;
        double beta = 0.0;
        double tracking_error = 0.0;
        double correlation = 0.0;
        double r_squared = 0.0;
        double information_ratio = 0.0;
    };
    BenchmarkStats compute_benchmark_stats(
        const std::vector<double>& strategy_returns,
        const std::vector<double>& benchmark_returns) const;

    // Statistical confidence
    struct ConfidenceStats {
        double ci_lower = 0.0;             // 95% CI lower bound
        double ci_upper = 0.0;             // 95% CI upper bound
        double t_statistic = 0.0;
        double p_value = 0.0;
        double deflated_sharpe = 0.0;      // DSR
    };
    ConfidenceStats compute_sharpe_confidence(
        const std::vector<double>& daily_returns,
        int num_trials = 1) const;

    // Block bootstrap for Sharpe ratio confidence interval
    std::pair<double, double> bootstrap_sharpe_ci(
        const std::vector<double>& daily_returns,
        double confidence = 0.95) const;

    // Deflated Sharpe Ratio (adjusts for multiple testing)
    // num_trials: number of strategy variants tested
    double deflated_sharpe_ratio(
        double observed_sharpe,
        int num_trials,
        int num_observations,
        double skewness = 0.0,
        double kurtosis = 3.0) const;

    // VaR and tail risk
    double historical_var(const std::vector<double>& returns, double alpha) const;
    double conditional_var(const std::vector<double>& returns, double alpha) const;

    // Distribution moments
    double compute_skewness(const std::vector<double>& returns) const;
    double compute_kurtosis(const std::vector<double>& returns) const;

    const Config& config() const { return config_; }

private:
    Config config_;

    // Daily risk-free rate from annual
    double daily_rf() const {
        return config_.risk_free_rate / config_.annualisation_factor;
    }

    // Annualisation scaling
    double ann_factor() const {
        return std::sqrt(static_cast<double>(config_.annualisation_factor));
    }
};

} // namespace trade
