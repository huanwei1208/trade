#pragma once

#include "trade/common/types.h"
#include "trade/common/config.h"
#include "trade/model/bar.h"
#include "trade/model/instrument.h"
#include "trade/model/market.h"

#include <memory>
#include <string>
#include <vector>
#include <unordered_map>
#include <functional>

namespace trade {

// Forward declarations
class IStrategy;
class PortfolioState;

// ============================================================================
// Order: instruction to buy or sell a symbol
// ============================================================================

enum class OrderType : uint8_t {
    kMarketOnOpen = 0,     // Execute at open price
    kLimitOnOpen  = 1,     // Limit order at open auction
    kVWAP         = 2,     // Target VWAP fill
    kTWAP         = 3,     // Target TWAP fill
};

struct Order {
    Symbol symbol;
    Side side = Side::kBuy;
    Volume quantity = 0;           // In shares (must be multiple of 100 for A-share buy)
    OrderType order_type = OrderType::kMarketOnOpen;
    double limit_price = 0.0;     // Only used for kLimitOnOpen
    double urgency = 0.5;         // 0.0 = patient, 1.0 = aggressive (for slippage models)
    std::string reason;            // Signal source / audit trail

    bool is_buy() const { return side == Side::kBuy; }
    bool is_sell() const { return side == Side::kSell; }
};

// ============================================================================
// OrderResult: outcome of an order execution attempt
// ============================================================================

enum class FillStatus : uint8_t {
    kFilled       = 0,
    kPartialFill  = 1,
    kRejected     = 2,
    kCancelled    = 3,
};

struct OrderResult {
    Order order;                   // Original order
    FillStatus status = FillStatus::kRejected;
    double fill_price = 0.0;      // Actual fill price (incl. slippage)
    Volume fill_qty = 0;          // Shares actually filled
    double commission = 0.0;      // Commission in yuan
    double stamp_tax = 0.0;       // Stamp tax in yuan (sell-only)
    double transfer_fee = 0.0;    // Transfer fee in yuan (SH only)
    double slippage_cost = 0.0;   // Slippage in yuan (fill_price - theoretical_price) * qty
    double total_cost() const { return commission + stamp_tax + transfer_fee; }
    std::string reject_reason;     // If rejected/cancelled, the reason

    bool is_filled() const {
        return status == FillStatus::kFilled || status == FillStatus::kPartialFill;
    }
};

// ============================================================================
// DailyRecord: snapshot of portfolio state at end of day
// ============================================================================

struct PositionRecord {
    Symbol symbol;
    Volume quantity = 0;
    double market_value = 0.0;
    double weight = 0.0;
    double unrealised_pnl = 0.0;
    double cost_basis = 0.0;
};

struct DailyRecord {
    Date date;
    double nav = 0.0;                        // Net asset value
    double daily_return = 0.0;               // Simple daily return
    double cumulative_return = 0.0;          // Cumulative return from start
    double drawdown = 0.0;                   // Current drawdown from peak
    double cash = 0.0;
    double gross_exposure = 0.0;             // Sum of |position market value|
    int num_positions = 0;
    double turnover = 0.0;                   // Daily turnover as fraction of NAV
    double total_cost = 0.0;                 // Total transaction costs today
    std::vector<PositionRecord> positions;   // End-of-day positions
    std::vector<OrderResult> fills;          // All order results today
};

// ============================================================================
// BacktestResult: full output of a backtest run
// ============================================================================

struct BacktestResult {
    std::string strategy_name;
    Date start_date;
    Date end_date;
    double initial_capital = 0.0;
    double final_nav = 0.0;
    int trading_days = 0;
    std::vector<DailyRecord> daily_records;

    // Quick accessors
    double total_return() const {
        return initial_capital > 0 ? (final_nav / initial_capital - 1.0) : 0.0;
    }

    std::vector<double> nav_series() const {
        std::vector<double> v;
        v.reserve(daily_records.size());
        for (const auto& r : daily_records) v.push_back(r.nav);
        return v;
    }

    std::vector<double> return_series() const {
        std::vector<double> v;
        v.reserve(daily_records.size());
        for (const auto& r : daily_records) v.push_back(r.daily_return);
        return v;
    }

    std::vector<double> drawdown_series() const {
        std::vector<double> v;
        v.reserve(daily_records.size());
        for (const auto& r : daily_records) v.push_back(r.drawdown);
        return v;
    }
};

// ============================================================================
// IMarketDataFeed: abstraction over historical Parquet vs live API
// ============================================================================
// Historical implementation reads from local Parquet files.
// Live implementation connects to a real-time market data API.

class IMarketDataFeed {
public:
    virtual ~IMarketDataFeed() = default;

    // Get a single daily bar for a symbol on a specific date.
    // Returns a default Bar (symbol.empty()) if no data exists.
    virtual Bar get_bar(const Symbol& symbol, Date date) = 0;

    // Get a range of daily bars for a symbol in [start, end].
    virtual std::vector<Bar> get_bars(const Symbol& symbol, Date start, Date end) = 0;

    // Get the full cross-sectional market snapshot for a date.
    virtual MarketSnapshot get_snapshot(Date date) = 0;

    // Check if data exists for a symbol on a given date (e.g., not suspended).
    virtual bool has_data(const Symbol& symbol, Date date) = 0;

    // Get instrument metadata for a symbol.
    virtual Instrument get_instrument(const Symbol& symbol) = 0;

    // Get all tradable symbols on a given date.
    virtual std::vector<Symbol> get_universe(Date date) = 0;
};

// ============================================================================
// IExecutionVenue: abstraction over BrokerSim vs live broker gateway
// ============================================================================
// BrokerSim implements A-share rules (T+1, limits, costs).
// Live implementation routes orders through a broker API.

class IExecutionVenue {
public:
    virtual ~IExecutionVenue() = default;

    // Execute a single order against the given bar (open auction fill).
    // Returns the fill result including slippage and costs.
    virtual OrderResult execute(const Order& order, const Bar& bar) = 0;

    // Execute a batch of orders (may apply cross-impact).
    virtual std::vector<OrderResult> execute_batch(
        const std::vector<Order>& orders,
        const MarketSnapshot& snapshot) {
        // Default: execute individually
        std::vector<OrderResult> results;
        results.reserve(orders.size());
        for (const auto& order : orders) {
            if (snapshot.has(order.symbol)) {
                results.push_back(execute(order, snapshot.bar(order.symbol)));
            } else {
                OrderResult r;
                r.order = order;
                r.status = FillStatus::kCancelled;
                r.reject_reason = "no market data";
                results.push_back(r);
            }
        }
        return results;
    }
};

// ============================================================================
// IClock: abstraction over historical time vs system clock
// ============================================================================
// Historical implementation advances through a pre-built trading calendar.
// Live implementation wraps system_clock with trading calendar checks.

class IClock {
public:
    virtual ~IClock() = default;

    // Current date in the simulation or live environment.
    virtual Date today() = 0;

    // Is the given date a trading day? (Respects holiday calendar.)
    virtual bool is_trading_day(Date d) = 0;

    // Next trading day after d.
    virtual Date next_trading_day(Date d) = 0;

    // Previous trading day before d.
    virtual Date prev_trading_day(Date d) = 0;

    // All trading days in [start, end].
    virtual std::vector<Date> trading_days_between(Date start, Date end) = 0;
};

// ============================================================================
// BacktestEngine: event-driven daily backtest engine
// ============================================================================
//
// Event loop (per trading day t):
//
//   Phase 1 — Pre-Open:
//     1. Advance clock to t.
//     2. Roll T+1 sellability (lots bought on t-1 become sellable today).
//     3. Check suspension/ST status from market data.
//     4. Load today's bars (open/high/low/close/volume).
//
//   Phase 2 — Open Auction:
//     1. Retrieve pending orders (generated at t-1 close).
//     2. Execute through IExecutionVenue:
//        - T+1 enforcement (can't sell lots bought today).
//        - Price limit blocking (limit up → no buy, limit down → no sell).
//        - Suspension → all orders cancelled.
//        - Liquidity checks (participation rate vs ADV).
//        - Slippage model application.
//     3. Update portfolio state with fills.
//
//   Phase 3 — Post-Close:
//     1. Mark-to-market all positions at close price.
//     2. Compute NAV, daily return, drawdown, VaR.
//     3. Run risk checks (position limits, exposure, concentration).
//     4. Update features using data available up to and including t.
//     5. Generate t+1 signals from strategy.
//     6. Optimize (if applicable) → generate orders for t+1.
//     7. Record DailyRecord.
//
// Key invariant: signals generated at t close → orders executed at t+1 open.
//

class BacktestEngine {
public:
    struct Config {
        double initial_capital = 1000000.0;
        int max_positions = 25;
        int min_positions = 15;
        double max_adv_participation = 0.12;    // Max fraction of ADV per order
        double rebalance_threshold = 0.01;      // Min weight deviation to trigger trade
        double alpha_cost_multiple = 1.5;       // Alpha must exceed cost by this multiple
        bool verbose = false;                    // Print progress to stdout
    };

    BacktestEngine(
        std::shared_ptr<IMarketDataFeed> market_data,
        std::shared_ptr<IExecutionVenue> execution,
        std::shared_ptr<IClock> clock);
    BacktestEngine(
        std::shared_ptr<IMarketDataFeed> market_data,
        std::shared_ptr<IExecutionVenue> execution,
        std::shared_ptr<IClock> clock,
        Config config);

    ~BacktestEngine();

    // -----------------------------------------------------------------------
    // Core interface
    // -----------------------------------------------------------------------

    // Run the backtest for a strategy over [start_date, end_date].
    // Returns the full backtest result with daily records.
    BacktestResult run(IStrategy& strategy, Date start_date, Date end_date);

    // -----------------------------------------------------------------------
    // Accessors
    // -----------------------------------------------------------------------

    const Config& config() const { return config_; }
    const PortfolioState& portfolio() const { return *portfolio_; }

    // Callback for progress reporting: (current_day, total_days)
    using ProgressCallback = std::function<void(int current, int total)>;
    void set_progress_callback(ProgressCallback cb) { progress_cb_ = std::move(cb); }

private:
    // Phase implementations
    void phase_pre_open(Date date);
    void phase_open_auction(Date date, const std::vector<Order>& pending_orders,
                            std::vector<OrderResult>& fills);
    DailyRecord phase_post_close(Date date, IStrategy& strategy,
                                  const std::vector<OrderResult>& fills,
                                  std::vector<Order>& next_orders);

    // Risk checks after mark-to-market
    void run_risk_checks(Date date);

    // Validate an order before execution
    bool validate_order(const Order& order, const Bar& bar, std::string& reason) const;

    // Apply participation rate limit
    Volume apply_participation_limit(const Order& order, const Bar& bar) const;

    // Record keeping
    DailyRecord build_daily_record(Date date, const std::vector<OrderResult>& fills) const;

    // Injected dependencies
    std::shared_ptr<IMarketDataFeed> market_data_;
    std::shared_ptr<IExecutionVenue> execution_;
    std::shared_ptr<IClock> clock_;

    // State
    Config config_;
    std::unique_ptr<PortfolioState> portfolio_;
    MarketSnapshot current_snapshot_;
    double peak_nav_ = 0.0;
    std::vector<Order> pending_orders_;         // Orders waiting for next open

    // Callback
    ProgressCallback progress_cb_;
};

} // namespace trade
