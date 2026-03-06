#include "trade/backtest/performance.h"
#include "trade/common/time_utils.h"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <random>
#include <vector>

namespace trade {

// ---------------------------------------------------------------------------
// Constructors
// ---------------------------------------------------------------------------

PerformanceCalculator::PerformanceCalculator() : config_{} {}
PerformanceCalculator::PerformanceCalculator(Config config) : config_(std::move(config)) {}

// ---------------------------------------------------------------------------
// Helper: compute mean of a vector
// ---------------------------------------------------------------------------
static double vec_mean(const std::vector<double>& v) {
    if (v.empty()) return 0.0;
    double sum = std::accumulate(v.begin(), v.end(), 0.0);
    return sum / static_cast<double>(v.size());
}

// ---------------------------------------------------------------------------
// Helper: compute standard deviation of a vector
// ---------------------------------------------------------------------------
static double vec_std(const std::vector<double>& v, double mean) {
    if (v.size() < 2) return 0.0;
    double sum_sq = 0.0;
    for (double x : v) {
        double d = x - mean;
        sum_sq += d * d;
    }
    return std::sqrt(sum_sq / static_cast<double>(v.size() - 1));
}

// ---------------------------------------------------------------------------
// Helper: compute downside deviation (only negative returns)
// ---------------------------------------------------------------------------
static double downside_deviation(const std::vector<double>& v, double target) {
    if (v.size() < 2) return 0.0;
    double sum_sq = 0.0;
    int count = 0;
    for (double x : v) {
        if (x < target) {
            double d = x - target;
            sum_sq += d * d;
            ++count;
        }
    }
    if (count == 0) return 0.0;
    return std::sqrt(sum_sq / static_cast<double>(v.size()));
}

// ---------------------------------------------------------------------------
// Helper: standard normal CDF approximation (Abramowitz & Stegun)
// ---------------------------------------------------------------------------
static double norm_cdf(double x) {
    // Rational approximation for the cumulative normal distribution
    const double a1 = 0.254829592;
    const double a2 = -0.284496736;
    const double a3 = 1.421413741;
    const double a4 = -1.453152027;
    const double a5 = 1.061405429;
    const double p  = 0.3275911;

    int sign = (x < 0) ? -1 : 1;
    x = std::abs(x) / std::sqrt(2.0);
    double t = 1.0 / (1.0 + p * x);
    double y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t
               * std::exp(-x * x);
    return 0.5 * (1.0 + sign * y);
}

// ============================================================================
// Core computation: full performance report
// ============================================================================

PerformanceReport PerformanceCalculator::compute(
    const BacktestResult& result) const {
    // No benchmark -- pass empty
    return compute(result, {});
}

PerformanceReport PerformanceCalculator::compute(
    const BacktestResult& result,
    const std::vector<double>& benchmark_returns) const {
    PerformanceReport report;

    if (result.daily_records.empty()) return report;

    // Extract return and NAV series
    auto returns = result.return_series();
    auto navs = result.nav_series();

    int n = static_cast<int>(returns.size());
    if (n == 0) return report;

    // -----------------------------------------------------------------------
    // Return metrics
    // -----------------------------------------------------------------------
    report.cumulative_return = cumulative_return(returns);
    report.annualised_return = annualised_return(returns);
    report.cagr = report.annualised_return;  // Same for daily returns
    report.monthly_returns = monthly_return_heatmap(result.daily_records);

    // -----------------------------------------------------------------------
    // Drawdown analysis
    // -----------------------------------------------------------------------
    auto dd_info = analyse_drawdowns(navs);
    report.max_drawdown = dd_info.max_drawdown;
    report.max_drawdown_duration = dd_info.max_drawdown_duration;
    report.avg_drawdown = dd_info.avg_drawdown;

    // Set drawdown dates from indices
    if (dd_info.peak_index >= 0 && dd_info.peak_index < n) {
        report.max_drawdown_start = result.daily_records[dd_info.peak_index].date;
    }
    if (dd_info.trough_index >= 0 && dd_info.trough_index < n) {
        report.max_drawdown_end = result.daily_records[dd_info.trough_index].date;
    }
    if (dd_info.recovery_index >= 0 && dd_info.recovery_index < n) {
        report.max_drawdown_recovery =
            result.daily_records[dd_info.recovery_index].date;
    }

    // -----------------------------------------------------------------------
    // Risk-adjusted metrics
    // -----------------------------------------------------------------------
    report.sharpe_ratio = sharpe_ratio(returns);
    report.sortino_ratio = sortino_ratio(returns);
    report.calmar_ratio = calmar_ratio(returns, dd_info.max_drawdown);

    // -----------------------------------------------------------------------
    // Trading statistics
    // -----------------------------------------------------------------------
    auto trade_stats = compute_trade_stats(result.daily_records);
    report.win_rate = trade_stats.win_rate;
    report.profit_loss_ratio = trade_stats.profit_loss_ratio;
    report.profit_factor = trade_stats.profit_factor;
    report.avg_holding_days = trade_stats.avg_holding_days;
    report.total_trades = trade_stats.total_trades;
    report.winning_trades = trade_stats.winning_trades;
    report.losing_trades = trade_stats.losing_trades;
    report.avg_trade_pnl = trade_stats.avg_trade_pnl;
    report.largest_win = trade_stats.largest_win;
    report.largest_loss = trade_stats.largest_loss;

    // -----------------------------------------------------------------------
    // Turnover and cost metrics
    // -----------------------------------------------------------------------
    double total_turnover = 0.0;
    double total_costs = 0.0;
    int total_fills = 0;
    for (const auto& rec : result.daily_records) {
        total_turnover += rec.turnover;
        total_costs += rec.total_cost;
        for (const auto& fill : rec.fills) {
            if (fill.is_filled()) ++total_fills;
        }
    }
    report.total_turnover = total_turnover;
    report.avg_daily_turnover = n > 0 ? total_turnover / n : 0.0;
    report.total_costs = total_costs;
    report.total_trades_count = total_fills;
    report.avg_cost_per_trade = total_fills > 0
                                ? total_costs / total_fills : 0.0;

    // Cost drag: annualised cost as fraction of capital
    double years = static_cast<double>(n)
                   / static_cast<double>(config_.annualisation_factor);
    report.cost_drag = (years > 0.0 && result.initial_capital > 0.0)
                       ? total_costs / (result.initial_capital * years)
                       : 0.0;

    // -----------------------------------------------------------------------
    // Benchmark-relative metrics
    // -----------------------------------------------------------------------
    if (!benchmark_returns.empty()) {
        // Ensure same length
        size_t len = std::min(returns.size(), benchmark_returns.size());
        std::vector<double> strat_r(returns.begin(),
                                     returns.begin() + len);
        std::vector<double> bench_r(benchmark_returns.begin(),
                                     benchmark_returns.begin() + len);

        auto bench_stats = compute_benchmark_stats(strat_r, bench_r);
        report.alpha = bench_stats.alpha;
        report.beta = bench_stats.beta;
        report.tracking_error = bench_stats.tracking_error;
        report.correlation = bench_stats.correlation;
        report.r_squared = bench_stats.r_squared;
        report.information_ratio = bench_stats.information_ratio;

        report.benchmark_return = annualised_return(bench_r);
        report.active_return = report.annualised_return
                               - report.benchmark_return;
        report.benchmark_sharpe = sharpe_ratio(bench_r);
    }

    // -----------------------------------------------------------------------
    // Statistical confidence
    // -----------------------------------------------------------------------
    auto conf = compute_sharpe_confidence(returns, 1);
    report.sharpe_t_statistic = conf.t_statistic;
    report.sharpe_p_value = conf.p_value;
    report.deflated_sharpe_ratio = conf.deflated_sharpe;

    auto ci = bootstrap_sharpe_ci(returns, 0.95);
    report.sharpe_bootstrap_ci_lower = ci.first;
    report.sharpe_bootstrap_ci_upper = ci.second;

    // -----------------------------------------------------------------------
    // VaR / Tail risk
    // -----------------------------------------------------------------------
    report.var_95 = historical_var(returns, 0.05);
    report.var_99 = historical_var(returns, 0.01);
    report.cvar_95 = conditional_var(returns, 0.05);
    report.skewness = compute_skewness(returns);
    report.kurtosis = compute_kurtosis(returns);

    // -----------------------------------------------------------------------
    // Exposure metrics
    // -----------------------------------------------------------------------
    double sum_positions = 0.0;
    double sum_exposure = 0.0;
    double sum_cash_wt = 0.0;
    for (const auto& rec : result.daily_records) {
        sum_positions += rec.num_positions;
        sum_exposure += rec.gross_exposure;
        double nav_val = rec.nav > 0.0 ? rec.nav : 1.0;
        sum_cash_wt += rec.cash / nav_val;
    }
    report.avg_num_positions = n > 0 ? sum_positions / n : 0.0;
    report.avg_gross_exposure = n > 0 ? sum_exposure / n : 0.0;
    report.avg_cash_weight = n > 0 ? sum_cash_wt / n : 0.0;

    return report;
}

// ============================================================================
// Return metrics
// ============================================================================

double PerformanceCalculator::annualised_return(
    const std::vector<double>& daily_returns) const {
    if (daily_returns.empty()) return 0.0;

    // Geometric compound
    double cum = 1.0;
    for (double r : daily_returns) {
        cum *= (1.0 + r);
    }

    if (cum <= 0.0) return -1.0;  // Total loss

    double n = static_cast<double>(daily_returns.size());
    double years = n / static_cast<double>(config_.annualisation_factor);

    if (years <= 0.0) return 0.0;

    // Annualised return = (cum)^(1/years) - 1
    return std::pow(cum, 1.0 / years) - 1.0;
}

double PerformanceCalculator::cumulative_return(
    const std::vector<double>& daily_returns) const {
    double cum = 1.0;
    for (double r : daily_returns) cum *= (1.0 + r);
    return cum - 1.0;
}

std::unordered_map<int, std::array<double, 12>>
PerformanceCalculator::monthly_return_heatmap(
    const std::vector<DailyRecord>& records) const {
    if (records.empty()) return {};

    // Group daily returns by year and month
    // monthly_cum[year][month-1] = cumulative product of (1 + daily_return)
    std::unordered_map<int, std::array<double, 12>> result;

    // Initialize tracking of cumulative products
    struct MonthTracker {
        double cum = 1.0;
        bool has_data = false;
    };
    std::unordered_map<int, std::array<MonthTracker, 12>> trackers;

    for (const auto& rec : records) {
        int year = date_year(rec.date);
        int month = date_month(rec.date);  // 1-12

        if (month < 1 || month > 12) continue;

        auto& tracker = trackers[year][month - 1];
        tracker.cum *= (1.0 + rec.daily_return);
        tracker.has_data = true;
    }

    // Convert cumulative products to monthly returns
    for (auto& [year, months] : trackers) {
        std::array<double, 12> monthly_rets{};
        for (int m = 0; m < 12; ++m) {
            if (months[m].has_data) {
                monthly_rets[m] = months[m].cum - 1.0;
            } else {
                monthly_rets[m] = 0.0;
            }
        }
        result[year] = monthly_rets;
    }

    return result;
}

// ============================================================================
// Risk-adjusted metrics
// ============================================================================

double PerformanceCalculator::sharpe_ratio(
    const std::vector<double>& daily_returns) const {
    if (daily_returns.size() < 2) return 0.0;

    double rf = daily_rf();
    double mean_excess = 0.0;
    for (double r : daily_returns) {
        mean_excess += (r - rf);
    }
    mean_excess /= static_cast<double>(daily_returns.size());

    double std_dev = 0.0;
    for (double r : daily_returns) {
        double d = (r - rf) - mean_excess;
        std_dev += d * d;
    }
    std_dev = std::sqrt(std_dev
                        / static_cast<double>(daily_returns.size() - 1));

    if (std_dev < 1e-15) return 0.0;

    // Annualise: Sharpe * sqrt(252)
    return (mean_excess / std_dev) * ann_factor();
}

double PerformanceCalculator::sortino_ratio(
    const std::vector<double>& daily_returns) const {
    if (daily_returns.size() < 2) return 0.0;

    double rf = daily_rf();
    double mean_excess = 0.0;
    for (double r : daily_returns) {
        mean_excess += (r - rf);
    }
    mean_excess /= static_cast<double>(daily_returns.size());

    // Downside deviation: sqrt of mean squared negative deviations
    double dd = downside_deviation(daily_returns, rf);

    if (dd < 1e-15) return 0.0;

    return (mean_excess / dd) * ann_factor();
}

double PerformanceCalculator::calmar_ratio(
    const std::vector<double>& daily_returns,
    double max_dd) const {
    if (max_dd <= 1e-15) return 0.0;
    return annualised_return(daily_returns) / max_dd;
}

double PerformanceCalculator::information_ratio(
    const std::vector<double>& active_returns) const {
    if (active_returns.size() < 2) return 0.0;

    double mean = vec_mean(active_returns);
    double sd = vec_std(active_returns, mean);
    if (sd < 1e-15) return 0.0;

    return (mean / sd) * ann_factor();
}

// ============================================================================
// Drawdown analysis
// ============================================================================

PerformanceCalculator::DrawdownInfo
PerformanceCalculator::analyse_drawdowns(
    const std::vector<double>& nav_series) const {
    DrawdownInfo info;
    if (nav_series.empty()) return info;

    double peak = nav_series[0];
    int peak_idx = 0;
    double max_dd = 0.0;
    int max_dd_peak_idx = 0;
    int max_dd_trough_idx = 0;

    // For tracking all drawdown periods
    double sum_dd = 0.0;
    int dd_count = 0;
    bool in_drawdown = false;
    [[maybe_unused]] int dd_start = 0;
    int max_dd_duration = 0;
    int current_dd_start = 0;

    for (int i = 0; i < static_cast<int>(nav_series.size()); ++i) {
        double nav = nav_series[i];

        if (nav > peak) {
            // New peak -- end of any current drawdown period
            if (in_drawdown) {
                int duration = i - current_dd_start;
                if (duration > max_dd_duration) {
                    max_dd_duration = duration;
                }
            }
            peak = nav;
            peak_idx = i;
            in_drawdown = false;
        }

        double dd = (peak > 0.0) ? (peak - nav) / peak : 0.0;

        if (dd > 0.0) {
            if (!in_drawdown) {
                in_drawdown = true;
                current_dd_start = peak_idx;
            }
            sum_dd += dd;
            ++dd_count;
        }

        if (dd > max_dd) {
            max_dd = dd;
            max_dd_peak_idx = peak_idx;
            max_dd_trough_idx = i;
        }
    }

    // Check if still in drawdown at the end
    if (in_drawdown) {
        int duration = static_cast<int>(nav_series.size()) - current_dd_start;
        if (duration > max_dd_duration) {
            max_dd_duration = duration;
        }
    }

    info.max_drawdown = max_dd;
    info.max_drawdown_duration = max_dd_duration;
    info.avg_drawdown = dd_count > 0 ? sum_dd / dd_count : 0.0;
    info.peak_index = max_dd_peak_idx;
    info.trough_index = max_dd_trough_idx;

    // Check for recovery after max drawdown
    double peak_at_max_dd = nav_series[max_dd_peak_idx];
    info.recovery_index = -1;
    for (int i = max_dd_trough_idx + 1;
         i < static_cast<int>(nav_series.size()); ++i) {
        if (nav_series[i] >= peak_at_max_dd) {
            info.recovery_index = i;
            break;
        }
    }

    return info;
}

// ============================================================================
// Trading statistics
// ============================================================================

PerformanceCalculator::TradeStats
PerformanceCalculator::compute_trade_stats(
    const std::vector<DailyRecord>& records) const {
    TradeStats stats;

    // Collect all filled trades and their P&L
    // We approximate round-trip trades from daily fills.
    // A buy followed by a sell of the same symbol constitutes a round-trip.
    // For simplicity, we track P&L from sell fills using fill_price vs
    // the position's average cost at time of sell.

    [[maybe_unused]] std::vector<double> trade_pnls;
    [[maybe_unused]] double gross_profit = 0.0;
    [[maybe_unused]] double gross_loss = 0.0;

    for (const auto& rec : records) {
        for (const auto& fill : rec.fills) {
            if (!fill.is_filled()) continue;
            if (fill.order.side != Side::kSell) continue;

            // Each sell fill represents a completed (partial) trade.
            // P&L is embedded in the fill's slippage + commission info.
            // We approximate: sell_amount - cost_basis - costs
            // Since we don't have cost_basis directly, we track from
            // the portfolio's realised P&L changes.

            // For trade stats, we use fill amount minus estimated cost
            // This is a simplification; real tracking would need
            // position-level entry/exit tracking.
            // We'll count each sell fill as a trade.
            [[maybe_unused]] double trade_amount = fill.fill_price
                                  * static_cast<double>(fill.fill_qty);
            [[maybe_unused]] double costs = fill.total_cost() + fill.slippage_cost;

            // We can't precisely compute P&L without the cost basis,
            // but we can count the trade and use other signals.
            ++stats.total_trades;
        }
    }

    // Better approach: use daily returns to estimate trade quality.
    // Look at net P&L from each day's fills by examining realised P&L.
    // Since individual trade P&L tracking requires position-level entry/exit,
    // we approximate using daily record data.

    // Count winning and losing days as a proxy for trade win rate
    int winning_days = 0;
    int losing_days = 0;
    double sum_winning = 0.0;
    double sum_losing = 0.0;
    double max_win = 0.0;
    double max_loss = 0.0;

    for (const auto& rec : records) {
        if (rec.daily_return > 1e-8) {
            ++winning_days;
            sum_winning += rec.daily_return;
            max_win = std::max(max_win, rec.daily_return);
        } else if (rec.daily_return < -1e-8) {
            ++losing_days;
            sum_losing += std::abs(rec.daily_return);
            max_loss = std::max(max_loss, std::abs(rec.daily_return));
        }
    }

    int total_active_days = winning_days + losing_days;
    stats.winning_trades = winning_days;
    stats.losing_trades = losing_days;
    stats.win_rate = total_active_days > 0
                     ? static_cast<double>(winning_days) / total_active_days
                     : 0.0;

    double avg_win = winning_days > 0 ? sum_winning / winning_days : 0.0;
    double avg_loss = losing_days > 0 ? sum_losing / losing_days : 0.0;

    stats.profit_loss_ratio = avg_loss > 0.0 ? avg_win / avg_loss : 0.0;
    stats.profit_factor = sum_losing > 0.0 ? sum_winning / sum_losing : 0.0;
    stats.largest_win = max_win;
    stats.largest_loss = max_loss;

    // Average P&L per trade (daily basis)
    stats.avg_trade_pnl = total_active_days > 0
        ? (sum_winning - sum_losing) / total_active_days : 0.0;

    // Average holding days: approximate from total positions held
    double total_position_days = 0.0;
    for (const auto& rec : records) {
        total_position_days += rec.num_positions;
    }
    stats.avg_holding_days = stats.total_trades > 0
        ? total_position_days / std::max(stats.total_trades, 1) : 0.0;

    return stats;
}

// ============================================================================
// Benchmark regression (CAPM)
// ============================================================================

PerformanceCalculator::BenchmarkStats
PerformanceCalculator::compute_benchmark_stats(
    const std::vector<double>& strategy_returns,
    const std::vector<double>& benchmark_returns) const {
    BenchmarkStats stats;

    size_t n = std::min(strategy_returns.size(), benchmark_returns.size());
    if (n < 3) return stats;

    double rf = daily_rf();

    // Excess returns
    std::vector<double> excess_strat(n), excess_bench(n), active_ret(n);
    for (size_t i = 0; i < n; ++i) {
        excess_strat[i] = strategy_returns[i] - rf;
        excess_bench[i] = benchmark_returns[i] - rf;
        active_ret[i] = strategy_returns[i] - benchmark_returns[i];
    }

    // CAPM regression: excess_strat = alpha + beta * excess_bench + eps
    double mean_s = vec_mean(excess_strat);
    double mean_b = vec_mean(excess_bench);

    double cov_sb = 0.0;
    double var_b = 0.0;
    for (size_t i = 0; i < n; ++i) {
        double ds = excess_strat[i] - mean_s;
        double db = excess_bench[i] - mean_b;
        cov_sb += ds * db;
        var_b += db * db;
    }

    if (var_b < 1e-15) return stats;

    stats.beta = cov_sb / var_b;
    double daily_alpha = mean_s - stats.beta * mean_b;
    stats.alpha = daily_alpha * config_.annualisation_factor;

    // Tracking error = annualised std of active returns
    double active_mean = vec_mean(active_ret);
    double active_std = vec_std(active_ret, active_mean);
    stats.tracking_error = active_std * ann_factor();

    // Correlation
    double var_s = 0.0;
    for (size_t i = 0; i < n; ++i) {
        double ds = excess_strat[i] - mean_s;
        var_s += ds * ds;
    }
    if (var_s > 1e-15 && var_b > 1e-15) {
        stats.correlation = cov_sb / std::sqrt(var_s * var_b);
    }

    // R-squared
    stats.r_squared = stats.correlation * stats.correlation;

    // Information ratio
    stats.information_ratio = stats.tracking_error > 1e-15
        ? (active_mean * config_.annualisation_factor) / stats.tracking_error
        : 0.0;

    return stats;
}

// ============================================================================
// Statistical confidence
// ============================================================================

PerformanceCalculator::ConfidenceStats
PerformanceCalculator::compute_sharpe_confidence(
    const std::vector<double>& daily_returns,
    int num_trials) const {
    ConfidenceStats stats;

    int n = static_cast<int>(daily_returns.size());
    if (n < 3) return stats;

    double sr = sharpe_ratio(daily_returns);
    double skew = compute_skewness(daily_returns);
    double kurt = compute_kurtosis(daily_returns);

    // Standard error of Sharpe ratio
    // SE(SR) = sqrt((1 + 0.5*SR^2 - skew*SR + (kurt-3)/4 * SR^2) / n)
    // (Lo, 2002 correction for non-normality)
    double sr_daily = sr / ann_factor();  // De-annualise
    double se_sq = (1.0
                    + 0.5 * sr_daily * sr_daily
                    - skew * sr_daily
                    + (kurt - 3.0) / 4.0 * sr_daily * sr_daily)
                   / static_cast<double>(n);
    double se = std::sqrt(std::max(se_sq, 0.0));

    // T-statistic for Sharpe > 0
    stats.t_statistic = (se > 1e-15) ? sr_daily / se : 0.0;

    // P-value (one-sided)
    stats.p_value = 1.0 - norm_cdf(stats.t_statistic);

    // 95% confidence interval (annualised)
    double se_ann = se * ann_factor();
    stats.ci_lower = sr - 1.96 * se_ann;
    stats.ci_upper = sr + 1.96 * se_ann;

    // Deflated Sharpe Ratio
    stats.deflated_sharpe = deflated_sharpe_ratio(sr, num_trials, n,
                                                    skew, kurt);

    return stats;
}

std::pair<double, double> PerformanceCalculator::bootstrap_sharpe_ci(
    const std::vector<double>& daily_returns,
    double confidence) const {
    int n = static_cast<int>(daily_returns.size());
    if (n < 10) return {0.0, 0.0};

    int block_size = config_.bootstrap_block_size;
    int num_samples = config_.bootstrap_samples;

    // Block bootstrap: resample blocks of consecutive returns
    std::mt19937 rng(42);  // Fixed seed for reproducibility
    [[maybe_unused]] int num_blocks = (n + block_size - 1) / block_size;

    std::vector<double> bootstrap_sharpes;
    bootstrap_sharpes.reserve(num_samples);

    std::uniform_int_distribution<int> block_dist(0, n - block_size);

    for (int s = 0; s < num_samples; ++s) {
        std::vector<double> sample_returns;
        sample_returns.reserve(n);

        while (static_cast<int>(sample_returns.size()) < n) {
            int start = block_dist(rng);
            int end = std::min(start + block_size, n);
            for (int i = start; i < end; ++i) {
                sample_returns.push_back(daily_returns[i]);
                if (static_cast<int>(sample_returns.size()) >= n) break;
            }
        }

        double sr = sharpe_ratio(sample_returns);
        bootstrap_sharpes.push_back(sr);
    }

    // Sort and extract percentiles
    std::sort(bootstrap_sharpes.begin(), bootstrap_sharpes.end());

    double alpha = (1.0 - confidence) / 2.0;
    int lower_idx = static_cast<int>(alpha * num_samples);
    int upper_idx = static_cast<int>((1.0 - alpha) * num_samples);

    lower_idx = std::max(0, std::min(lower_idx, num_samples - 1));
    upper_idx = std::max(0, std::min(upper_idx, num_samples - 1));

    return {bootstrap_sharpes[lower_idx], bootstrap_sharpes[upper_idx]};
}

double PerformanceCalculator::deflated_sharpe_ratio(
    double observed_sharpe, int num_trials, int num_observations,
    double skewness, double kurtosis) const {
    // DSR from Bailey & Lopez de Prado (2014)
    //
    // DSR = Phi(
    //   (SR_observed - SR_expected_max) / SE(SR)
    // )
    //
    // SR_expected_max ≈ sqrt(2 * ln(num_trials)) * (1 - gamma/ln(num_trials))
    //                  + gamma / (2 * sqrt(ln(num_trials)))
    // where gamma ≈ 0.5772 (Euler-Mascheroni constant)

    if (num_trials <= 0 || num_observations < 2) return 0.0;

    double n = static_cast<double>(num_observations);
    double gamma_em = 0.5772156649015329;

    // Expected maximum Sharpe from num_trials independent trials
    // (assuming each trial produces a Sharpe from N(0, 1/sqrt(n)))
    double expected_max_sr = 0.0;
    if (num_trials > 1) {
        double ln_k = std::log(static_cast<double>(num_trials));
        if (ln_k > 0.0) {
            expected_max_sr = std::sqrt(2.0 * ln_k)
                * (1.0 - gamma_em / (2.0 * ln_k))
                + gamma_em / (2.0 * std::sqrt(2.0 * ln_k));
        }
    }
    // The expected_max_sr is in daily (de-annualised) units
    // Convert observed Sharpe to daily
    double sr_daily = observed_sharpe / ann_factor();
    expected_max_sr /= std::sqrt(n);  // Scale to same unit

    // Standard error of Sharpe with skewness/kurtosis correction
    double se_sq = (1.0
                    + 0.5 * sr_daily * sr_daily
                    - skewness * sr_daily
                    + (kurtosis - 3.0) / 4.0 * sr_daily * sr_daily)
                   / n;
    double se = std::sqrt(std::max(se_sq, 1e-15));

    // DSR = P(SR < observed | H0: SR = expected_max)
    double z = (sr_daily - expected_max_sr) / se;
    return norm_cdf(z);
}

// ============================================================================
// VaR and tail risk
// ============================================================================

double PerformanceCalculator::historical_var(
    const std::vector<double>& returns, double alpha) const {
    if (returns.empty()) return 0.0;

    std::vector<double> sorted = returns;
    std::sort(sorted.begin(), sorted.end());

    int idx = static_cast<int>(alpha * static_cast<double>(sorted.size()));
    idx = std::max(0, std::min(idx,
                               static_cast<int>(sorted.size()) - 1));

    // VaR is reported as a positive number (loss)
    return -sorted[idx];
}

double PerformanceCalculator::conditional_var(
    const std::vector<double>& returns, double alpha) const {
    if (returns.empty()) return 0.0;

    std::vector<double> sorted = returns;
    std::sort(sorted.begin(), sorted.end());

    int cutoff = static_cast<int>(alpha * static_cast<double>(sorted.size()));
    cutoff = std::max(1, cutoff);

    double sum = 0.0;
    for (int i = 0; i < cutoff; ++i) {
        sum += sorted[i];
    }

    // CVaR is the average of returns below VaR threshold (positive = loss)
    return -(sum / static_cast<double>(cutoff));
}

// ============================================================================
// Distribution moments
// ============================================================================

double PerformanceCalculator::compute_skewness(
    const std::vector<double>& returns) const {
    int n = static_cast<int>(returns.size());
    if (n < 3) return 0.0;

    double mean = vec_mean(returns);
    double m2 = 0.0, m3 = 0.0;
    for (double r : returns) {
        double d = r - mean;
        m2 += d * d;
        m3 += d * d * d;
    }
    m2 /= n;
    m3 /= n;

    if (m2 < 1e-15) return 0.0;

    double sd = std::sqrt(m2);
    // Sample skewness with bias correction
    double skew = m3 / (sd * sd * sd);
    return skew * std::sqrt(static_cast<double>(n * (n - 1)))
           / static_cast<double>(n - 2);
}

double PerformanceCalculator::compute_kurtosis(
    const std::vector<double>& returns) const {
    int n = static_cast<int>(returns.size());
    if (n < 4) return 3.0;  // Normal kurtosis

    double mean = vec_mean(returns);
    double m2 = 0.0, m4 = 0.0;
    for (double r : returns) {
        double d = r - mean;
        m2 += d * d;
        m4 += d * d * d * d;
    }
    m2 /= n;
    m4 /= n;

    if (m2 < 1e-15) return 3.0;

    // Excess kurtosis
    double kurt = m4 / (m2 * m2);

    // Bias correction for sample
    double nn = static_cast<double>(n);
    double corrected = ((nn - 1.0) / ((nn - 2.0) * (nn - 3.0)))
                       * ((nn + 1.0) * kurt - 3.0 * (nn - 1.0));
    return corrected + 3.0;  // Return kurtosis (not excess)
}

} // namespace trade
