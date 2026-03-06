#pragma once

#include "trade/common/types.h"
#include "trade/model/bar.h"
#include "trade/model/instrument.h"

#include <string>
#include <unordered_map>
#include <vector>

namespace trade {

// Forward declaration from backtest_engine.h
struct Order;

// ============================================================================
// PreTradeChecker: pre-trade risk and feasibility checks
// ============================================================================
// Every order passes through this checker before reaching the execution venue.
// Checks enforce A-share trading rules and risk limits that are not captured
// by the portfolio optimiser.
//
// Check catalogue:
//   1. T+1 sellability:   sell_qty <= sellable_qty (lots bought today cannot
//                          be sold until the next trading day).
//   2. Price limit risk:  if the current price is approaching the daily price
//                          limit, reduce order size or reject.
//   3. Suspension check:  reject orders for stocks that are suspended or
//                          likely to be suspended (based on announced events).
//   4. Participation rate: order_qty <= max_participation * ADV_20d.
//                          Prevents excessive market impact on illiquid names.
//   5. Lot size:          buy orders must be a multiple of 100 shares.
//   6. Minimum order value: order notional must exceed a minimum threshold.
//
class PreTradeChecker {
public:
    // -----------------------------------------------------------------------
    // Configuration
    // -----------------------------------------------------------------------
    struct Config {
        // Participation rate
        double max_participation = 0.12;         // max fraction of 20d ADV per order

        // Price limit proximity: reject/reduce if within this % of limit
        double limit_proximity_warn_pct = 0.02;  // 2% -> warn and reduce
        double limit_proximity_reject_pct = 0.005; // 0.5% -> reject outright

        // Size reduction when approaching limit
        double limit_proximity_size_factor = 0.5; // reduce qty by this factor

        // Minimum order notional (yuan)
        double min_order_notional = 5000.0;

        // A-share lot size
        Volume lot_size = 100;
    };

    // -----------------------------------------------------------------------
    // Portfolio state (positions and sellability)
    // -----------------------------------------------------------------------
    struct PortfolioState {
        // Current holdings: symbol -> total shares held
        std::unordered_map<Symbol, Volume> holdings;

        // Sellable shares: symbol -> shares eligible for T+1 sell
        // (total holdings minus shares bought today)
        std::unordered_map<Symbol, Volume> sellable_qty;

        // Cash available
        double cash = 0.0;

        // Net asset value
        double nav = 0.0;
    };

    // -----------------------------------------------------------------------
    // Market data needed for pre-trade checks
    // -----------------------------------------------------------------------
    struct MarketData {
        // Current / latest bar
        std::unordered_map<Symbol, Bar> bars;

        // Instrument metadata (for board, status, limit prices)
        std::unordered_map<Symbol, Instrument> instruments;

        // 20-day average daily volume (yuan)
        std::unordered_map<Symbol, double> adv_20d;

        // Limit prices (if not computable from bar + board)
        std::unordered_map<Symbol, double> limit_up;
        std::unordered_map<Symbol, double> limit_down;
    };

    // -----------------------------------------------------------------------
    // Pre-trade check result
    // -----------------------------------------------------------------------
    struct PreTradeResult {
        bool pass = false;                       // overall pass/fail
        Volume original_qty = 0;                 // quantity before adjustment
        Volume adjusted_qty = 0;                 // quantity after adjustment (may be reduced)
        std::string rejection_reason;            // non-empty if pass == false

        // Detailed check results
        struct CheckDetail {
            bool t1_sellable = true;             // T+1 check passed
            bool price_limit_ok = true;          // not approaching limit
            bool not_suspended = true;           // not suspended
            bool participation_ok = true;        // within ADV participation limit
            bool lot_size_ok = true;             // buy is round lot
            bool min_notional_ok = true;         // meets minimum notional
        } detail;

        // Warnings (non-fatal issues)
        std::vector<std::string> warnings;
    };

    PreTradeChecker() : config_{} {}
    explicit PreTradeChecker(Config cfg) : config_(std::move(cfg)) {}

    // -----------------------------------------------------------------------
    // Core interface
    // -----------------------------------------------------------------------

    // Check a single order against current portfolio state and market data.
    // Returns a PreTradeResult indicating pass/fail and any quantity adjustment.
    PreTradeResult check(
        const Order& order,
        const PortfolioState& portfolio_state,
        const MarketData& market_data) const;

    // Check a batch of orders. Returns results in the same order.
    std::vector<PreTradeResult> check_batch(
        const std::vector<Order>& orders,
        const PortfolioState& portfolio_state,
        const MarketData& market_data) const;

    // -----------------------------------------------------------------------
    // Individual checks (can be used standalone)
    // -----------------------------------------------------------------------

    // T+1 sellability: can we sell this quantity?
    bool check_t1_sellable(
        const Symbol& symbol,
        Volume sell_qty,
        const PortfolioState& state) const;

    // Price limit proximity: is the stock approaching its price limit?
    // Returns: 0 = safe, 1 = warn (reduce size), 2 = reject
    int check_price_limit(
        const Symbol& symbol,
        Side side,
        const MarketData& market_data) const;

    // Participation rate: is the order within ADV limits?
    // Returns the maximum allowed quantity based on participation cap.
    Volume max_participation_qty(
        const Symbol& symbol,
        double price,
        const MarketData& market_data) const;

    // Round quantity to lot size (for buy orders)
    Volume round_to_lot(Volume qty) const;

    const Config& config() const { return config_; }
    void set_config(const Config& cfg) { config_ = cfg; }

private:
    Config config_;
};

} // namespace trade
