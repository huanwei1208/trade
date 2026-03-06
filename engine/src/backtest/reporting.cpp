#include "trade/backtest/reporting.h"
#include "trade/backtest/strategy.h"
#include "trade/common/time_utils.h"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <numeric>
#include <sstream>
#include <unordered_map>

namespace trade {

// ---------------------------------------------------------------------------
// Constructors
// ---------------------------------------------------------------------------

BacktestReporter::BacktestReporter() : config_{} {}
BacktestReporter::BacktestReporter(Config config) : config_(std::move(config)) {}

// ============================================================================
// Report generation
// ============================================================================

BacktestReport BacktestReporter::generate(
    const BacktestResult& result,
    const IStrategy& strategy) const {
    return generate(result, strategy, {});
}

BacktestReport BacktestReporter::generate(
    const BacktestResult& result,
    const IStrategy& strategy,
    const std::vector<double>& benchmark_returns) const {

    BacktestReport report;

    // --- Metadata ---
    report.strategy_name = strategy.name();
    report.strategy_version = strategy.version();
    report.strategy_params = strategy.params_summary();
    report.start_date = result.start_date;
    report.end_date = result.end_date;
    report.initial_capital = result.initial_capital;
    report.trading_days = result.trading_days;
    report.benchmark_name = config_.benchmark_name;

    // Generate timestamp
    auto now = std::chrono::system_clock::now();
    report.generated_at = format_timestamp(now);

    // --- Performance metrics ---
    PerformanceCalculator perf_calc;
    if (!benchmark_returns.empty()) {
        report.performance = perf_calc.compute(result, benchmark_returns);
    } else {
        report.performance = perf_calc.compute(result);
    }

    // --- Equity curve ---
    report.equity_curve = build_equity_curve(result.daily_records,
                                              benchmark_returns);

    // --- Drawdown curve ---
    for (const auto& rec : result.daily_records) {
        report.drawdown_curve.emplace_back(rec.date, rec.drawdown);
    }

    // --- Trade details ---
    if (config_.include_trade_details) {
        report.trades = build_trade_details(result.daily_records);
    }

    // --- Performance attribution ---
    if (config_.include_daily_attribution && !benchmark_returns.empty()) {
        report.daily_attribution = build_attribution(
            result.daily_records, benchmark_returns,
            report.performance.beta);
        report.attribution_summary = summarise_attribution(
            report.daily_attribution);
    }

    // --- Position history ---
    if (config_.include_position_history) {
        report.position_history = build_position_history(result.daily_records);
    }

    // --- Cost summary ---
    report.cost_summary = build_cost_summary(result.daily_records,
                                              result.initial_capital,
                                              result.trading_days);

    return report;
}

BacktestReport BacktestReporter::generate(
    const BacktestResult& result,
    const IStrategy& strategy,
    const std::vector<double>& benchmark_returns,
    const ValidationResult& validation) const {
    auto report = generate(result, strategy, benchmark_returns);
    report.validation = validation;
    report.overfit_tests = validation.overfit_tests;
    return report;
}

// ============================================================================
// JSON serialization
// ============================================================================

// Helper: escape a string for JSON
static std::string json_escape(const std::string& s) {
    std::string out;
    out.reserve(s.size() + 10);
    for (char c : s) {
        switch (c) {
            case '"':  out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:   out += c; break;
        }
    }
    return out;
}

// Helper: format double with fixed precision for JSON
static std::string json_num(double v, int prec = 6) {
    if (std::isnan(v) || std::isinf(v)) return "null";
    std::ostringstream ss;
    ss << std::fixed << std::setprecision(prec) << v;
    return ss.str();
}

std::string BacktestReporter::to_json(const BacktestReport& report) {
    std::ostringstream j;

    j << "{\n";

    // --- Metadata ---
    j << "  \"metadata\": {\n";
    j << "    \"strategy_name\": \"" << json_escape(report.strategy_name) << "\",\n";
    j << "    \"strategy_version\": \"" << json_escape(report.strategy_version) << "\",\n";
    j << "    \"strategy_params\": \"" << json_escape(report.strategy_params) << "\",\n";
    j << "    \"start_date\": \"" << format_date(report.start_date) << "\",\n";
    j << "    \"end_date\": \"" << format_date(report.end_date) << "\",\n";
    j << "    \"initial_capital\": " << json_num(report.initial_capital, 2) << ",\n";
    j << "    \"trading_days\": " << report.trading_days << ",\n";
    j << "    \"benchmark_name\": \"" << json_escape(report.benchmark_name) << "\",\n";
    j << "    \"generated_at\": \"" << json_escape(report.generated_at) << "\"\n";
    j << "  },\n";

    // --- Performance ---
    const auto& p = report.performance;
    j << "  \"performance\": {\n";
    j << "    \"annualised_return\": " << json_num(p.annualised_return) << ",\n";
    j << "    \"cumulative_return\": " << json_num(p.cumulative_return) << ",\n";
    j << "    \"cagr\": " << json_num(p.cagr) << ",\n";
    j << "    \"sharpe_ratio\": " << json_num(p.sharpe_ratio) << ",\n";
    j << "    \"sortino_ratio\": " << json_num(p.sortino_ratio) << ",\n";
    j << "    \"calmar_ratio\": " << json_num(p.calmar_ratio) << ",\n";
    j << "    \"information_ratio\": " << json_num(p.information_ratio) << ",\n";
    j << "    \"max_drawdown\": " << json_num(p.max_drawdown) << ",\n";
    j << "    \"max_drawdown_duration\": " << p.max_drawdown_duration << ",\n";
    j << "    \"avg_drawdown\": " << json_num(p.avg_drawdown) << ",\n";
    j << "    \"win_rate\": " << json_num(p.win_rate) << ",\n";
    j << "    \"profit_factor\": " << json_num(p.profit_factor) << ",\n";
    j << "    \"profit_loss_ratio\": " << json_num(p.profit_loss_ratio) << ",\n";
    j << "    \"total_trades\": " << p.total_trades << ",\n";
    j << "    \"winning_trades\": " << p.winning_trades << ",\n";
    j << "    \"losing_trades\": " << p.losing_trades << ",\n";
    j << "    \"avg_trade_pnl\": " << json_num(p.avg_trade_pnl) << ",\n";
    j << "    \"largest_win\": " << json_num(p.largest_win) << ",\n";
    j << "    \"largest_loss\": " << json_num(p.largest_loss) << ",\n";
    j << "    \"alpha\": " << json_num(p.alpha) << ",\n";
    j << "    \"beta\": " << json_num(p.beta) << ",\n";
    j << "    \"tracking_error\": " << json_num(p.tracking_error) << ",\n";
    j << "    \"correlation\": " << json_num(p.correlation) << ",\n";
    j << "    \"r_squared\": " << json_num(p.r_squared) << ",\n";
    j << "    \"var_95\": " << json_num(p.var_95) << ",\n";
    j << "    \"var_99\": " << json_num(p.var_99) << ",\n";
    j << "    \"cvar_95\": " << json_num(p.cvar_95) << ",\n";
    j << "    \"skewness\": " << json_num(p.skewness) << ",\n";
    j << "    \"kurtosis\": " << json_num(p.kurtosis) << ",\n";
    j << "    \"deflated_sharpe_ratio\": " << json_num(p.deflated_sharpe_ratio) << ",\n";
    j << "    \"sharpe_t_statistic\": " << json_num(p.sharpe_t_statistic) << ",\n";
    j << "    \"sharpe_p_value\": " << json_num(p.sharpe_p_value) << ",\n";
    j << "    \"avg_daily_turnover\": " << json_num(p.avg_daily_turnover) << ",\n";
    j << "    \"total_costs\": " << json_num(p.total_costs, 2) << ",\n";
    j << "    \"cost_drag\": " << json_num(p.cost_drag) << ",\n";
    j << "    \"avg_num_positions\": " << json_num(p.avg_num_positions, 1) << ",\n";
    j << "    \"avg_gross_exposure\": " << json_num(p.avg_gross_exposure, 2) << ",\n";
    j << "    \"avg_cash_weight\": " << json_num(p.avg_cash_weight) << "\n";
    j << "  },\n";

    // --- Equity curve ---
    j << "  \"equity_curve\": [\n";
    for (size_t i = 0; i < report.equity_curve.size(); ++i) {
        const auto& pt = report.equity_curve[i];
        j << "    {"
          << "\"date\": \"" << format_date(pt.date) << "\", "
          << "\"strategy_nav\": " << json_num(pt.strategy_nav) << ", "
          << "\"benchmark_nav\": " << json_num(pt.benchmark_nav) << ", "
          << "\"active_nav\": " << json_num(pt.active_nav) << ", "
          << "\"drawdown\": " << json_num(pt.drawdown)
          << "}";
        if (i + 1 < report.equity_curve.size()) j << ",";
        j << "\n";
    }
    j << "  ],\n";

    // --- Monthly returns ---
    j << "  \"monthly_returns\": {\n";
    {
        auto sorted_years = std::vector<int>();
        for (const auto& [year, _] : p.monthly_returns) {
            sorted_years.push_back(year);
        }
        std::sort(sorted_years.begin(), sorted_years.end());

        for (size_t yi = 0; yi < sorted_years.size(); ++yi) {
            int year = sorted_years[yi];
            const auto& months = p.monthly_returns.at(year);
            j << "    \"" << year << "\": [";
            for (int m = 0; m < 12; ++m) {
                j << json_num(months[m]);
                if (m < 11) j << ", ";
            }
            j << "]";
            if (yi + 1 < sorted_years.size()) j << ",";
            j << "\n";
        }
    }
    j << "  },\n";

    // --- Trade log (first 1000 trades) ---
    j << "  \"trades\": [\n";
    {
        size_t max_trades = std::min(report.trades.size(), size_t(1000));
        for (size_t i = 0; i < max_trades; ++i) {
            const auto& t = report.trades[i];
            j << "    {"
              << "\"symbol\": \"" << json_escape(t.symbol) << "\", "
              << "\"side\": \"" << (t.side == Side::kBuy ? "BUY" : "SELL") << "\", "
              << "\"entry_date\": \"" << format_date(t.entry_date) << "\", "
              << "\"exit_date\": \"" << format_date(t.exit_date) << "\", "
              << "\"entry_price\": " << json_num(t.entry_price, 4) << ", "
              << "\"exit_price\": " << json_num(t.exit_price, 4) << ", "
              << "\"quantity\": " << t.quantity << ", "
              << "\"pnl\": " << json_num(t.pnl, 2) << ", "
              << "\"return_pct\": " << json_num(t.return_pct) << ", "
              << "\"holding_days\": " << json_num(t.holding_days, 0) << ", "
              << "\"commission\": " << json_num(t.commission, 2) << ", "
              << "\"entry_reason\": \"" << json_escape(t.entry_reason) << "\", "
              << "\"exit_reason\": \"" << json_escape(t.exit_reason) << "\""
              << "}";
            if (i + 1 < max_trades) j << ",";
            j << "\n";
        }
    }
    j << "  ],\n";

    // --- Cost summary ---
    j << "  \"cost_summary\": {\n";
    j << "    \"total_commission\": " << json_num(report.cost_summary.total_commission, 2) << ",\n";
    j << "    \"total_stamp_tax\": " << json_num(report.cost_summary.total_stamp_tax, 2) << ",\n";
    j << "    \"total_transfer_fee\": " << json_num(report.cost_summary.total_transfer_fee, 2) << ",\n";
    j << "    \"total_slippage\": " << json_num(report.cost_summary.total_slippage, 2) << ",\n";
    j << "    \"total_costs\": " << json_num(report.cost_summary.total_costs, 2) << ",\n";
    j << "    \"cost_as_annual_return_drag\": " << json_num(report.cost_summary.cost_as_annual_return_drag) << "\n";
    j << "  },\n";

    // --- Attribution summary ---
    j << "  \"attribution\": {\n";
    j << "    \"total_return\": " << json_num(report.attribution_summary.total_return) << ",\n";
    j << "    \"market_contribution\": " << json_num(report.attribution_summary.market_contribution) << ",\n";
    j << "    \"alpha_contribution\": " << json_num(report.attribution_summary.alpha_contribution) << ",\n";
    j << "    \"cost_drag\": " << json_num(report.attribution_summary.cost_drag) << ",\n";
    j << "    \"timing_contribution\": " << json_num(report.attribution_summary.timing_contribution) << "\n";
    j << "  },\n";

    // --- Overfit tests ---
    const auto& ot = report.overfit_tests;
    j << "  \"overfit_tests\": {\n";
    j << "    \"dsr\": " << json_num(ot.dsr) << ",\n";
    j << "    \"dsr_pass\": " << (ot.dsr_pass ? "true" : "false") << ",\n";
    j << "    \"pbo\": " << json_num(ot.pbo) << ",\n";
    j << "    \"pbo_pass\": " << (ot.pbo_pass ? "true" : "false") << ",\n";
    j << "    \"mbl_years\": " << json_num(ot.mbl_years, 1) << ",\n";
    j << "    \"actual_years\": " << json_num(ot.actual_years, 1) << ",\n";
    j << "    \"mbl_pass\": " << (ot.mbl_pass ? "true" : "false") << ",\n";
    j << "    \"fdr\": " << json_num(ot.fdr) << ",\n";
    j << "    \"fdr_pass\": " << (ot.fdr_pass ? "true" : "false") << ",\n";
    j << "    \"bootstrap_ci_lower\": " << json_num(ot.bootstrap_ci_lower) << ",\n";
    j << "    \"bootstrap_ci_upper\": " << json_num(ot.bootstrap_ci_upper) << ",\n";
    j << "    \"bootstrap_pass\": " << (ot.bootstrap_pass ? "true" : "false") << ",\n";
    j << "    \"all_pass\": " << (ot.all_pass() ? "true" : "false") << "\n";
    j << "  }\n";

    j << "}\n";

    return j.str();
}

void BacktestReporter::to_json_file(const BacktestReport& report,
                                     const std::string& path) {
    std::ofstream ofs(path);
    if (ofs.is_open()) {
        ofs << to_json(report);
        ofs.close();
    }
}

// ============================================================================
// CSV serialization
// ============================================================================

std::string BacktestReporter::equity_curve_to_csv(
    const BacktestReport& report) {
    std::ostringstream csv;
    csv << "date,strategy_nav,benchmark_nav,active_nav,drawdown\n";

    for (const auto& pt : report.equity_curve) {
        csv << format_date(pt.date) << ","
            << std::fixed << std::setprecision(6)
            << pt.strategy_nav << ","
            << pt.benchmark_nav << ","
            << pt.active_nav << ","
            << pt.drawdown << "\n";
    }

    return csv.str();
}

std::string BacktestReporter::trades_to_csv(const BacktestReport& report) {
    std::ostringstream csv;
    csv << "symbol,side,entry_date,exit_date,entry_price,exit_price,"
        << "quantity,pnl,return_pct,holding_days,commission,slippage_cost,"
        << "entry_reason,exit_reason\n";

    for (const auto& t : report.trades) {
        csv << t.symbol << ","
            << (t.side == Side::kBuy ? "BUY" : "SELL") << ","
            << format_date(t.entry_date) << ","
            << format_date(t.exit_date) << ","
            << std::fixed << std::setprecision(4)
            << t.entry_price << ","
            << t.exit_price << ","
            << t.quantity << ","
            << std::setprecision(2)
            << t.pnl << ","
            << std::setprecision(6)
            << t.return_pct << ","
            << std::setprecision(0)
            << t.holding_days << ","
            << std::setprecision(2)
            << t.commission << ","
            << t.slippage_cost << ","
            << "\"" << t.entry_reason << "\","
            << "\"" << t.exit_reason << "\"\n";
    }

    return csv.str();
}

std::string BacktestReporter::monthly_returns_to_csv(
    const BacktestReport& report) {
    std::ostringstream csv;
    csv << "year,jan,feb,mar,apr,may,jun,jul,aug,sep,oct,nov,dec,annual\n";

    auto sorted_years = std::vector<int>();
    for (const auto& [year, _] : report.performance.monthly_returns) {
        sorted_years.push_back(year);
    }
    std::sort(sorted_years.begin(), sorted_years.end());

    for (int year : sorted_years) {
        const auto& months = report.performance.monthly_returns.at(year);

        // Compute annual return as product of monthly returns
        double annual = 1.0;
        for (int m = 0; m < 12; ++m) {
            annual *= (1.0 + months[m]);
        }
        annual -= 1.0;

        csv << year;
        for (int m = 0; m < 12; ++m) {
            csv << "," << std::fixed << std::setprecision(4)
                << months[m];
        }
        csv << "," << std::fixed << std::setprecision(4) << annual << "\n";
    }

    return csv.str();
}

// ============================================================================
// Text summary
// ============================================================================

std::string BacktestReporter::to_text_summary(const BacktestReport& report) {
    std::ostringstream ss;
    const auto& p = report.performance;

    ss << "============================================================\n";
    ss << " Backtest Report: " << report.strategy_name << "\n";
    ss << "============================================================\n";
    ss << "\n";

    // Metadata
    ss << "Period:           " << format_date(report.start_date) << " to "
       << format_date(report.end_date) << "\n";
    ss << "Trading Days:     " << report.trading_days << "\n";
    ss << "Initial Capital:  " << std::fixed << std::setprecision(0)
       << report.initial_capital << " yuan\n";
    ss << "Benchmark:        " << report.benchmark_name << "\n";
    ss << "\n";

    // Return metrics
    ss << "--- Return Metrics ---\n";
    ss << "Annualised Return:  " << std::fixed << std::setprecision(2)
       << (p.annualised_return * 100) << "%\n";
    ss << "Cumulative Return:  " << (p.cumulative_return * 100) << "%\n";
    ss << "CAGR:               " << (p.cagr * 100) << "%\n";
    ss << "\n";

    // Risk-adjusted
    ss << "--- Risk-Adjusted Metrics ---\n";
    ss << "Sharpe Ratio:       " << std::setprecision(3) << p.sharpe_ratio << "\n";
    ss << "Sortino Ratio:      " << p.sortino_ratio << "\n";
    ss << "Calmar Ratio:       " << p.calmar_ratio << "\n";
    ss << "Information Ratio:  " << p.information_ratio << "\n";
    ss << "\n";

    // Drawdown
    ss << "--- Drawdown ---\n";
    ss << "Max Drawdown:       " << std::setprecision(2)
       << (p.max_drawdown * 100) << "%\n";
    ss << "Max DD Duration:    " << p.max_drawdown_duration << " days\n";
    ss << "Avg Drawdown:       " << (p.avg_drawdown * 100) << "%\n";
    ss << "\n";

    // Trading
    ss << "--- Trading Metrics ---\n";
    ss << "Win Rate:           " << std::setprecision(1)
       << (p.win_rate * 100) << "%\n";
    ss << "Profit Factor:      " << std::setprecision(2)
       << p.profit_factor << "\n";
    ss << "Profit/Loss Ratio:  " << p.profit_loss_ratio << "\n";
    ss << "Total Trades:       " << p.total_trades << "\n";
    ss << "Avg Daily Turnover: " << std::setprecision(2)
       << (p.avg_daily_turnover * 100) << "%\n";
    ss << "\n";

    // Benchmark
    if (p.beta != 0.0 || p.alpha != 0.0) {
        ss << "--- Benchmark (" << report.benchmark_name << ") ---\n";
        ss << "Alpha:              " << std::setprecision(2)
           << (p.alpha * 100) << "%\n";
        ss << "Beta:               " << std::setprecision(3) << p.beta << "\n";
        ss << "Tracking Error:     " << std::setprecision(2)
           << (p.tracking_error * 100) << "%\n";
        ss << "Correlation:        " << std::setprecision(3) << p.correlation << "\n";
        ss << "R-squared:          " << std::setprecision(3) << p.r_squared << "\n";
        ss << "\n";
    }

    // Tail risk
    ss << "--- Tail Risk ---\n";
    ss << "VaR 95%:            " << std::setprecision(2)
       << (p.var_95 * 100) << "%\n";
    ss << "VaR 99%:            " << (p.var_99 * 100) << "%\n";
    ss << "CVaR 95%:           " << (p.cvar_95 * 100) << "%\n";
    ss << "Skewness:           " << std::setprecision(3) << p.skewness << "\n";
    ss << "Kurtosis:           " << p.kurtosis << "\n";
    ss << "\n";

    // Costs
    ss << "--- Costs ---\n";
    ss << "Total Commission:   " << std::setprecision(2)
       << report.cost_summary.total_commission << " yuan\n";
    ss << "Total Stamp Tax:    " << report.cost_summary.total_stamp_tax << " yuan\n";
    ss << "Total Slippage:     " << report.cost_summary.total_slippage << " yuan\n";
    ss << "Cost Drag (annual): " << std::setprecision(2)
       << (report.cost_summary.cost_as_annual_return_drag * 100) << "%\n";
    ss << "\n";

    // Confidence
    ss << "--- Statistical Confidence ---\n";
    ss << "Sharpe t-stat:      " << std::setprecision(3)
       << p.sharpe_t_statistic << "\n";
    ss << "Sharpe p-value:     " << std::setprecision(4) << p.sharpe_p_value << "\n";
    ss << "DSR:                " << std::setprecision(3)
       << p.deflated_sharpe_ratio << "\n";
    ss << "Bootstrap 95% CI:   [" << std::setprecision(3)
       << p.sharpe_bootstrap_ci_lower << ", "
       << p.sharpe_bootstrap_ci_upper << "]\n";
    ss << "\n";

    ss << "============================================================\n";

    return ss.str();
}

// ============================================================================
// Component builders
// ============================================================================

std::vector<EquityCurvePoint> BacktestReporter::build_equity_curve(
    const std::vector<DailyRecord>& records,
    const std::vector<double>& benchmark_returns) const {

    std::vector<EquityCurvePoint> curve;
    if (records.empty()) return curve;

    curve.reserve(records.size());

    double initial_nav = records[0].nav;
    if (initial_nav <= 0.0) initial_nav = 1.0;

    [[maybe_unused]] double strategy_cum = 1.0;
    double benchmark_cum = 1.0;
    double peak_strat = 1.0;

    for (size_t i = 0; i < records.size(); ++i) {
        EquityCurvePoint pt;
        pt.date = records[i].date;

        // Strategy NAV indexed to 1.0
        pt.strategy_nav = records[i].nav / initial_nav;
        strategy_cum = pt.strategy_nav;

        // Benchmark NAV indexed to 1.0
        if (i < benchmark_returns.size()) {
            benchmark_cum *= (1.0 + benchmark_returns[i]);
        }
        pt.benchmark_nav = benchmark_cum;

        // Active (excess) NAV
        pt.active_nav = pt.strategy_nav - pt.benchmark_nav;

        // Drawdown from peak
        if (pt.strategy_nav > peak_strat) {
            peak_strat = pt.strategy_nav;
        }
        pt.drawdown = (peak_strat > 0.0)
                      ? (peak_strat - pt.strategy_nav) / peak_strat
                      : 0.0;

        curve.push_back(pt);
    }

    return curve;
}

std::vector<TradeDetail> BacktestReporter::build_trade_details(
    const std::vector<DailyRecord>& records) const {

    std::vector<TradeDetail> trades;

    // Track open positions: symbol -> (entry_date, entry_price, qty, reason)
    struct OpenPosition {
        Date entry_date;
        double entry_price = 0.0;
        Volume quantity = 0;
        std::string entry_reason;
        double total_commission = 0.0;
        double total_slippage = 0.0;
    };
    std::unordered_map<Symbol, OpenPosition> open_positions;

    for (const auto& rec : records) {
        for (const auto& fill : rec.fills) {
            if (!fill.is_filled()) continue;

            if (fill.order.side == Side::kBuy) {
                // Open or add to position
                auto& pos = open_positions[fill.order.symbol];
                if (pos.quantity == 0) {
                    pos.entry_date = rec.date;
                    pos.entry_price = fill.fill_price;
                    pos.entry_reason = fill.order.reason;
                }
                // Weighted average entry price
                double old_value = pos.entry_price
                                   * static_cast<double>(pos.quantity);
                double new_value = fill.fill_price
                                   * static_cast<double>(fill.fill_qty);
                pos.quantity += fill.fill_qty;
                if (pos.quantity > 0) {
                    pos.entry_price = (old_value + new_value)
                                      / static_cast<double>(pos.quantity);
                }
                pos.total_commission += fill.commission;
                pos.total_slippage += fill.slippage_cost;

            } else {
                // Close or reduce position
                auto it = open_positions.find(fill.order.symbol);
                if (it == open_positions.end()) continue;

                auto& pos = it->second;
                Volume sell_qty = std::min(fill.fill_qty, pos.quantity);

                // Create trade detail
                TradeDetail td;
                td.symbol = fill.order.symbol;
                td.side = Side::kBuy;  // Round-trip is a buy
                td.entry_date = pos.entry_date;
                td.exit_date = rec.date;
                td.entry_price = pos.entry_price;
                td.exit_price = fill.fill_price;
                td.quantity = sell_qty;
                td.pnl = (fill.fill_price - pos.entry_price)
                          * static_cast<double>(sell_qty)
                          - fill.commission - fill.stamp_tax;
                td.return_pct = pos.entry_price > 0.0
                    ? (fill.fill_price / pos.entry_price - 1.0) : 0.0;
                td.holding_days = static_cast<double>(
                    (rec.date - pos.entry_date).count());
                td.commission = pos.total_commission + fill.commission;
                td.slippage_cost = pos.total_slippage + fill.slippage_cost;
                td.entry_reason = pos.entry_reason;
                td.exit_reason = fill.order.reason;

                trades.push_back(td);

                // Update open position
                pos.quantity -= sell_qty;
                if (pos.quantity <= 0) {
                    open_positions.erase(it);
                }
            }
        }
    }

    return trades;
}

std::vector<DailyAttribution> BacktestReporter::build_attribution(
    const std::vector<DailyRecord>& records,
    const std::vector<double>& benchmark_returns,
    double beta) const {

    std::vector<DailyAttribution> attribution;
    attribution.reserve(records.size());

    for (size_t i = 0; i < records.size(); ++i) {
        DailyAttribution da;
        da.date = records[i].date;
        da.total_return = records[i].daily_return;

        // Market contribution = beta * benchmark_return
        double bench_ret = (i < benchmark_returns.size())
                           ? benchmark_returns[i] : 0.0;
        da.market_return = beta * bench_ret;

        // Cost contribution (negative)
        double nav = records[i].nav > 0.0 ? records[i].nav : 1.0;
        da.cost_return = -records[i].total_cost / nav;

        // Cash timing: cash_weight * (0 - portfolio_return)
        // Simplified: if holding cash, miss out on market returns
        double cash_wt = records[i].cash / nav;
        da.timing_return = -cash_wt * bench_ret;

        // Alpha = residual
        da.alpha_return = da.total_return - da.market_return
                          - da.cost_return - da.timing_return;

        attribution.push_back(da);
    }

    return attribution;
}

AttributionSummary BacktestReporter::summarise_attribution(
    const std::vector<DailyAttribution>& daily) const {

    AttributionSummary summary;
    if (daily.empty()) return summary;

    // Cumulative sums (simple addition for daily returns)
    double cum_total = 1.0, cum_market = 0.0, cum_alpha = 0.0;
    double cum_cost = 0.0, cum_timing = 0.0;

    for (const auto& da : daily) {
        cum_total *= (1.0 + da.total_return);
        cum_market += da.market_return;
        cum_alpha += da.alpha_return;
        cum_cost += da.cost_return;
        cum_timing += da.timing_return;
    }

    summary.total_return = cum_total - 1.0;
    summary.market_contribution = cum_market;
    summary.alpha_contribution = cum_alpha;
    summary.cost_drag = cum_cost;
    summary.timing_contribution = cum_timing;
    summary.residual = summary.total_return - cum_market - cum_alpha
                       - cum_cost - cum_timing;

    return summary;
}

std::vector<BacktestReport::DailyPositionSnapshot>
BacktestReporter::build_position_history(
    const std::vector<DailyRecord>& records) const {

    std::vector<BacktestReport::DailyPositionSnapshot> history;
    history.reserve(records.size());

    for (const auto& rec : records) {
        BacktestReport::DailyPositionSnapshot snap;
        snap.date = rec.date;
        snap.total_positions = rec.num_positions;

        // Sort positions by weight (descending) and take top N
        auto sorted_positions = rec.positions;
        std::sort(sorted_positions.begin(), sorted_positions.end(),
                  [](const PositionRecord& a, const PositionRecord& b) {
                      return a.weight > b.weight;
                  });

        int top_n = std::min(config_.top_n_positions,
                             static_cast<int>(sorted_positions.size()));
        snap.top_positions.assign(sorted_positions.begin(),
                                   sorted_positions.begin() + top_n);

        // Concentration metrics
        double top5_weight = 0.0;
        double top10_weight = 0.0;
        for (int i = 0; i < static_cast<int>(sorted_positions.size()); ++i) {
            if (i < 5) top5_weight += sorted_positions[i].weight;
            if (i < 10) top10_weight += sorted_positions[i].weight;
        }
        snap.concentration_top5 = top5_weight;
        snap.concentration_top10 = top10_weight;

        history.push_back(snap);
    }

    return history;
}

BacktestReport::CostSummary BacktestReporter::build_cost_summary(
    const std::vector<DailyRecord>& records,
    double initial_capital, int trading_days) const {

    BacktestReport::CostSummary summary;

    for (const auto& rec : records) {
        for (const auto& fill : rec.fills) {
            if (!fill.is_filled()) continue;
            summary.total_commission += fill.commission;
            summary.total_stamp_tax += fill.stamp_tax;
            summary.total_transfer_fee += fill.transfer_fee;
            summary.total_slippage += fill.slippage_cost;
        }
    }

    summary.total_costs = summary.total_commission
                          + summary.total_stamp_tax
                          + summary.total_transfer_fee
                          + summary.total_slippage;

    // Annualised cost drag
    double years = static_cast<double>(trading_days) / 252.0;
    if (years > 0.0 && initial_capital > 0.0) {
        summary.cost_as_annual_return_drag = summary.total_costs
                                             / (initial_capital * years);
    }

    return summary;
}

} // namespace trade
