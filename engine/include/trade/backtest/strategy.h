#pragma once

#include "trade/backtest/backtest_engine.h"
#include "trade/backtest/portfolio_state.h"
#include "trade/model/market.h"

#include <string>
#include <vector>

namespace trade {

// ============================================================================
// IStrategy: abstract strategy interface for the backtest engine
// ============================================================================
//
// Design principles:
//
// 1. Cross-Sectional Vectorized Input:
//    The strategy receives the full MarketSnapshot (all stocks for a date),
//    NOT individual bar-by-bar callbacks. This matches the alpha research
//    workflow where signals are computed cross-sectionally (rank, z-score,
//    neutralize across the universe).
//
// 2. Signal at t Close, Execution at t+1 Open:
//    on_market_close() is called after the day's bars are finalised. The
//    strategy generates orders based on data available up to and including t.
//    These orders are held by the engine and executed at t+1's open auction.
//    This eliminates look-ahead bias.
//
// 3. Shared Code with Decision Engine:
//    The same strategy logic (feature computation -> signal -> portfolio
//    optimisation -> order generation) is used in both backtest mode and
//    the live decision engine. The IStrategy interface is the shared
//    abstraction. Only the execution venue differs (BrokerSim vs live broker).
//
// 4. State Management:
//    Strategies can maintain internal state (e.g., signal history, running
//    covariance estimates). The on_init() / on_end() lifecycle hooks allow
//    proper setup and teardown. The engine guarantees on_init() is called
//    before any on_market_* call, and on_end() after the last trading day.
//

class IStrategy {
public:
    virtual ~IStrategy() = default;

    // -----------------------------------------------------------------------
    // Lifecycle
    // -----------------------------------------------------------------------

    // Called once before the backtest starts.
    // Use for initialisation: load models, pre-compute lookback data, etc.
    virtual void on_init(Date /*start_date*/, Date /*end_date*/,
                         double /*initial_capital*/) {}

    // Called once after the backtest ends.
    // Use for cleanup, final logging, etc.
    virtual void on_end(const BacktestResult& /*result*/) {}

    // -----------------------------------------------------------------------
    // Daily Callbacks
    // -----------------------------------------------------------------------

    // Called at market open (after Phase 1 pre-open, before Phase 2 execution).
    // The strategy can observe the opening snapshot but SHOULD NOT generate
    // orders here — orders are generated at close. This hook is for:
    //   - Logging opening state
    //   - Emergency cancellation logic
    //   - Intraday monitoring in live mode
    //
    // Returns: orders to cancel from the pending queue (by symbol).
    virtual std::vector<Symbol> on_market_open(
        Date /*date*/,
        const MarketSnapshot& /*snapshot*/) {
        return {};  // Default: no cancellations
    }

    // Called after market close (Phase 3 post-close).
    // This is the PRIMARY signal generation entry point.
    //
    // The strategy should:
    //   1. Update features using data up to and including today.
    //   2. Generate alpha signals (cross-sectional scores).
    //   3. Run portfolio optimisation (if applicable).
    //   4. Produce orders for TOMORROW's open execution.
    //
    // Parameters:
    //   date       - Today's date (data up to this date is available).
    //   snapshot   - Full market snapshot for today.
    //   portfolio  - Current portfolio state (after today's fills and MTM).
    //
    // Returns: vector of Orders to be executed at tomorrow's open.
    virtual std::vector<Order> on_market_close(
        Date date,
        const MarketSnapshot& snapshot,
        const PortfolioState& portfolio) = 0;

    // -----------------------------------------------------------------------
    // Metadata
    // -----------------------------------------------------------------------

    // Strategy name for reporting and identification.
    virtual std::string name() const = 0;

    // Strategy description (optional, for reports).
    virtual std::string description() const { return ""; }

    // Strategy version (optional, for tracking parameter changes).
    virtual std::string version() const { return "1.0.0"; }

    // Parameter summary for logging (e.g., "lookback=60, top_n=25").
    virtual std::string params_summary() const { return ""; }
};

// ============================================================================
// StrategyBase: convenience base class with common utilities
// ============================================================================
//
// Provides helper methods commonly needed by strategy implementations:
//   - Universe filtering (remove suspended, ST, new IPOs, illiquid)
//   - Signal-to-order conversion (rank signals → select top N → size orders)
//   - Turnover budgeting (limit daily turnover)
//

class StrategyBase : public IStrategy {
public:
    struct Config {
        int max_positions = 25;
        int min_positions = 15;
        double max_single_weight = 0.10;
        double max_turnover_per_day = 0.30;   // Max NAV fraction to trade
        double min_adv_participation = 0.08;
        double rebalance_threshold = 0.01;    // Min weight deviation to trade
        int min_listing_days = 120;           // Exclude new IPOs
        bool exclude_st = true;               // Exclude ST stocks
    };

    StrategyBase();
    explicit StrategyBase(Config config);

    const Config& strategy_config() const { return strategy_config_; }

protected:
    // -----------------------------------------------------------------------
    // Universe Filtering
    // -----------------------------------------------------------------------

    // Filter the snapshot to tradable symbols:
    //   - Not suspended
    //   - Not ST (if exclude_st)
    //   - Listed > min_listing_days
    //   - Has valid bar data (volume > 0, price > 0)
    std::vector<Symbol> filter_universe(
        const MarketSnapshot& snapshot, Date date) const;

    // -----------------------------------------------------------------------
    // Order Generation Helpers
    // -----------------------------------------------------------------------

    // Convert target weights to orders.
    // Compares target_weights with current portfolio and generates buy/sell
    // orders for the differences. Respects rebalance_threshold and turnover budget.
    std::vector<Order> weights_to_orders(
        const std::unordered_map<Symbol, double>& target_weights,
        const PortfolioState& portfolio,
        const MarketSnapshot& snapshot) const;

    // Select top N stocks by signal score and equal-weight them.
    // Returns: map of symbol -> target weight.
    std::unordered_map<Symbol, double> top_n_equal_weight(
        const std::unordered_map<Symbol, double>& signals,
        int n) const;

    // Select top N stocks by signal score and signal-weight them
    // (weight proportional to signal strength).
    std::unordered_map<Symbol, double> top_n_signal_weight(
        const std::unordered_map<Symbol, double>& signals,
        int n) const;

private:
    Config strategy_config_;
};

} // namespace trade
