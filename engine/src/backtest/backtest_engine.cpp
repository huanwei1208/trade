#include "trade/backtest/backtest_engine.h"
#include "trade/backtest/portfolio_state.h"
#include "trade/backtest/strategy.h"

#include <algorithm>
#include <cmath>
#include <iostream>
#include <numeric>

namespace trade {

// ---------------------------------------------------------------------------
// Constructors / Destructor
// ---------------------------------------------------------------------------

BacktestEngine::BacktestEngine(
    std::shared_ptr<IMarketDataFeed> market_data,
    std::shared_ptr<IExecutionVenue> execution,
    std::shared_ptr<IClock> clock)
    : market_data_(std::move(market_data))
    , execution_(std::move(execution))
    , clock_(std::move(clock))
    , config_{}
    , portfolio_(std::make_unique<PortfolioState>(config_.initial_capital))
    , peak_nav_(config_.initial_capital) {}

BacktestEngine::BacktestEngine(
    std::shared_ptr<IMarketDataFeed> market_data,
    std::shared_ptr<IExecutionVenue> execution,
    std::shared_ptr<IClock> clock,
    Config config)
    : market_data_(std::move(market_data))
    , execution_(std::move(execution))
    , clock_(std::move(clock))
    , config_(std::move(config))
    , portfolio_(std::make_unique<PortfolioState>(config_.initial_capital))
    , peak_nav_(config_.initial_capital) {}

BacktestEngine::~BacktestEngine() = default;

// ---------------------------------------------------------------------------
// Core: run the full backtest
// ---------------------------------------------------------------------------

BacktestResult BacktestEngine::run(IStrategy& strategy,
                                    Date start_date, Date end_date) {
    // Initialize result
    BacktestResult result;
    result.strategy_name = strategy.name();
    result.start_date = start_date;
    result.end_date = end_date;
    result.initial_capital = config_.initial_capital;

    // Reset portfolio to initial state
    portfolio_->reset(config_.initial_capital);
    peak_nav_ = config_.initial_capital;
    pending_orders_.clear();

    // Get all trading days in the backtest period
    std::vector<Date> trading_days =
        clock_->trading_days_between(start_date, end_date);

    if (trading_days.empty()) {
        result.final_nav = config_.initial_capital;
        result.trading_days = 0;
        return result;
    }

    // Notify strategy of backtest start
    strategy.on_init(start_date, end_date, config_.initial_capital);

    double prev_nav = config_.initial_capital;

    // Main simulation loop: iterate over each trading day
    for (int day_idx = 0; day_idx < static_cast<int>(trading_days.size());
         ++day_idx) {
        Date date = trading_days[day_idx];

        // Report progress
        if (progress_cb_) {
            progress_cb_(day_idx + 1,
                         static_cast<int>(trading_days.size()));
        }

        if (config_.verbose && day_idx % 50 == 0) {
            // Periodic progress output
        }

        // ==================================================================
        // Phase 1: Pre-Open
        // ==================================================================
        phase_pre_open(date);

        // ==================================================================
        // Phase 2: Open Auction -- execute pending orders from t-1 close
        // ==================================================================
        std::vector<OrderResult> fills;
        phase_open_auction(date, pending_orders_, fills);
        pending_orders_.clear();

        // Update portfolio state with fills
        Date next_td = (day_idx + 1 < static_cast<int>(trading_days.size()))
                        ? trading_days[day_idx + 1]
                        : clock_->next_trading_day(date);
        portfolio_->update_on_fills(fills, date, next_td);

        // ==================================================================
        // Phase 3: Post-Close
        // ==================================================================
        std::vector<Order> next_orders;
        DailyRecord record = phase_post_close(date, strategy, fills,
                                               next_orders);

        // Compute daily return
        double current_nav = portfolio_->total_nav();
        record.daily_return = (prev_nav > 0.0)
                              ? (current_nav / prev_nav - 1.0)
                              : 0.0;
        record.cumulative_return = (config_.initial_capital > 0.0)
                                   ? (current_nav / config_.initial_capital - 1.0)
                                   : 0.0;

        // Update peak NAV and drawdown
        if (current_nav > peak_nav_) {
            peak_nav_ = current_nav;
        }
        record.drawdown = (peak_nav_ > 0.0)
                          ? (peak_nav_ - current_nav) / peak_nav_
                          : 0.0;

        // Compute turnover: sum of absolute fill amounts / prev_nav
        double turnover_amount = 0.0;
        for (const auto& fill : fills) {
            if (fill.is_filled()) {
                turnover_amount += fill.fill_price
                                   * static_cast<double>(fill.fill_qty);
            }
        }
        record.turnover = (prev_nav > 0.0)
                          ? turnover_amount / prev_nav
                          : 0.0;

        // Compute total cost for the day
        double day_cost = 0.0;
        for (const auto& fill : fills) {
            day_cost += fill.total_cost();
        }
        record.total_cost = day_cost;

        // Store daily record
        result.daily_records.push_back(std::move(record));

        // Store next orders for execution tomorrow
        pending_orders_ = std::move(next_orders);
        prev_nav = current_nav;
    }

    // Finalize result
    result.final_nav = portfolio_->total_nav();
    result.trading_days = static_cast<int>(trading_days.size());

    // Notify strategy of backtest end
    strategy.on_end(result);

    return result;
}

// ---------------------------------------------------------------------------
// Phase 1: Pre-Open
// ---------------------------------------------------------------------------

void BacktestEngine::phase_pre_open(Date date) {
    // 1. Roll T+1 sellability (no-op in current design, but call for
    //    interface consistency and future optimisation)
    portfolio_->roll_sellability(date);

    // 2. Load today's market snapshot
    current_snapshot_ = market_data_->get_snapshot(date);

    // 3. Cleanup empty positions (housekeeping from previous sells)
    portfolio_->cleanup_empty_positions();
}

// ---------------------------------------------------------------------------
// Phase 2: Open Auction
// ---------------------------------------------------------------------------

void BacktestEngine::phase_open_auction(
    Date /*date*/,
    const std::vector<Order>& pending_orders,
    std::vector<OrderResult>& fills) {

    if (pending_orders.empty()) return;

    // Validate and filter orders
    std::vector<Order> valid_orders;
    valid_orders.reserve(pending_orders.size());

    for (const auto& order : pending_orders) {
        // Check if we have market data for this symbol
        if (!current_snapshot_.has(order.symbol)) {
            OrderResult r;
            r.order = order;
            r.status = FillStatus::kCancelled;
            r.reject_reason = "no market data";
            fills.push_back(r);
            continue;
        }

        const Bar& bar = current_snapshot_.bar(order.symbol);
        std::string reason;

        if (validate_order(order, bar, reason)) {
            // Apply participation limit to adjust quantity
            Volume adj_qty = apply_participation_limit(order, bar);
            if (adj_qty > 0) {
                Order adj_order = order;
                adj_order.quantity = adj_qty;
                valid_orders.push_back(std::move(adj_order));
            } else {
                OrderResult r;
                r.order = order;
                r.status = FillStatus::kRejected;
                r.reject_reason = "zero quantity after participation limit";
                fills.push_back(r);
            }
        } else {
            OrderResult r;
            r.order = order;
            r.status = FillStatus::kRejected;
            r.reject_reason = reason;
            fills.push_back(r);
        }
    }

    // Execute valid orders through the execution venue
    if (!valid_orders.empty()) {
        auto exec_results = execution_->execute_batch(valid_orders,
                                                       current_snapshot_);
        fills.insert(fills.end(), exec_results.begin(), exec_results.end());
    }
}

// ---------------------------------------------------------------------------
// Phase 3: Post-Close
// ---------------------------------------------------------------------------

DailyRecord BacktestEngine::phase_post_close(
    Date date, IStrategy& strategy,
    const std::vector<OrderResult>& fills,
    std::vector<Order>& next_orders) {

    // 1. Mark-to-market all positions at close price
    portfolio_->mark_to_market(current_snapshot_);

    // 2. Recompute position weights
    portfolio_->compute_weights();

    // 3. Run risk checks
    run_risk_checks(date);

    // 4. Build daily record (NAV, positions, etc.)
    DailyRecord record = build_daily_record(date, fills);

    // 5. Generate orders for tomorrow via strategy callback
    //    Strategy receives today's snapshot and current portfolio state.
    //    It returns orders to be executed at tomorrow's open.
    next_orders = strategy.on_market_close(date, current_snapshot_,
                                            *portfolio_);

    return record;
}

// ---------------------------------------------------------------------------
// Risk checks
// ---------------------------------------------------------------------------

void BacktestEngine::run_risk_checks(Date /*date*/) {
    // Check position count limits
    [[maybe_unused]] int n_pos = portfolio_->num_positions();

    // Check max single position concentration
    double nav = portfolio_->total_nav();
    if (nav <= 0.0) return;

    for (const auto& [sym, pos] : portfolio_->positions()) {
        if (pos.total_qty == 0) continue;
        double wt = pos.market_value / nav;

        // Log warning if single position exceeds soft limit
        if (wt > 0.10 && config_.verbose) {
            // Position concentration warning
        }
    }

    // Check drawdown
    double current_nav = portfolio_->total_nav();
    double dd = (peak_nav_ > 0.0)
                ? (peak_nav_ - current_nav) / peak_nav_
                : 0.0;

    if (dd > 0.20 && config_.verbose) {
        // Significant drawdown warning
    }
}

// ---------------------------------------------------------------------------
// Order validation
// ---------------------------------------------------------------------------

bool BacktestEngine::validate_order(const Order& order, const Bar& bar,
                                     std::string& reason) const {
    // Basic validation
    if (order.symbol.empty()) {
        reason = "empty symbol";
        return false;
    }

    if (order.quantity <= 0) {
        reason = "non-positive quantity";
        return false;
    }

    // Check bar validity
    if (!bar.is_valid()) {
        reason = "invalid bar data";
        return false;
    }

    // For buy orders, check minimum cash availability
    if (order.side == Side::kBuy) {
        double estimated_cost = bar.open * static_cast<double>(order.quantity);
        if (estimated_cost > portfolio_->cash() * 1.1) {
            // Allow slight over-estimation; BrokerSim will do exact check
            reason = "insufficient cash (pre-check)";
            return false;
        }
    }

    // For sell orders, check that we hold the stock
    if (order.side == Side::kSell) {
        if (!portfolio_->has_position(order.symbol)) {
            reason = "no position to sell";
            return false;
        }
    }

    return true;
}

// ---------------------------------------------------------------------------
// Participation limit
// ---------------------------------------------------------------------------

Volume BacktestEngine::apply_participation_limit(const Order& order,
                                                  const Bar& bar) const {
    if (bar.volume <= 0) return 0;

    double max_qty = config_.max_adv_participation
                     * static_cast<double>(bar.volume);
    Volume capped = std::min(order.quantity,
                             static_cast<Volume>(max_qty));
    return std::max(capped, static_cast<Volume>(0));
}

// ---------------------------------------------------------------------------
// Daily record construction
// ---------------------------------------------------------------------------

DailyRecord BacktestEngine::build_daily_record(
    Date date, const std::vector<OrderResult>& fills) const {
    DailyRecord record;
    record.date = date;
    record.nav = portfolio_->total_nav();
    record.cash = portfolio_->cash();
    record.gross_exposure = portfolio_->gross_exposure();
    record.num_positions = portfolio_->num_positions();

    // Snapshot current positions
    record.positions = portfolio_->snapshot();

    // Copy fills
    record.fills = fills;

    return record;
}

} // namespace trade
