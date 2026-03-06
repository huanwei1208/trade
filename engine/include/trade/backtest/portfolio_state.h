#pragma once

#include "trade/backtest/backtest_engine.h"
#include "trade/common/types.h"
#include "trade/model/bar.h"
#include "trade/model/market.h"

#include <deque>
#include <string>
#include <unordered_map>
#include <vector>

namespace trade {

// ============================================================================
// TaxLot: individual purchase lot for T+1 tracking and cost basis
// ============================================================================
//
// Each buy fill creates a new TaxLot. Lots are consumed FIFO on sell.
// The sellable_date is the next trading day after buy_date (T+1 rule).
//
// Example:
//   Day 1 (Monday):  Buy 500 shares → lot(buy_date=Mon, sellable_date=Tue)
//   Day 2 (Tuesday): Buy 300 shares → lot(buy_date=Tue, sellable_date=Wed)
//   Day 2 (Tuesday): Can sell up to 500 (lot 1 is sellable), lot 2 is locked.
//   Day 3 (Wednesday): Can sell up to 800 (both lots sellable).
//

struct TaxLot {
    Date buy_date;                // Date the lot was purchased
    Volume quantity = 0;          // Remaining shares in this lot
    double cost_price = 0.0;      // Per-share cost basis (incl. commission)
    Date sellable_date;           // First date this lot can be sold (buy_date + 1 trading day)

    // Is this lot sellable on the given date?
    bool is_sellable(Date today) const {
        return today >= sellable_date && quantity > 0;
    }

    // Total cost basis for remaining shares
    double total_cost() const {
        return cost_price * static_cast<double>(quantity);
    }
};

// ============================================================================
// Position: aggregated view of all lots for a single symbol
// ============================================================================

struct Position {
    Symbol symbol;
    Volume total_qty = 0;          // Sum of all lot quantities
    double avg_cost = 0.0;         // Weighted average cost per share
    double market_price = 0.0;     // Last mark-to-market price
    double market_value = 0.0;     // total_qty * market_price
    double unrealised_pnl = 0.0;   // market_value - total_cost
    double realised_pnl = 0.0;     // Accumulated realised P&L from sells
    double total_cost_basis = 0.0; // Sum of lot cost bases

    // Weight in portfolio (set by PortfolioState::compute_weights)
    double weight = 0.0;

    bool is_empty() const { return total_qty == 0; }
};

// ============================================================================
// PortfolioState: complete portfolio state with T+1 lot tracking
// ============================================================================
//
// Maintains:
//   - Cash balance
//   - Positions map: symbol -> Position (aggregated view)
//   - Tax lots: symbol -> deque<TaxLot> (per-lot detail, FIFO order)
//
// T+1 enforcement:
//   - sellable_qty(symbol, today): sum of lot quantities where sellable_date <= today
//   - unsellable_qty(symbol, today): sum of lot quantities where sellable_date > today
//   - roll_sellability(today): no-op in current design (sellability is date-checked)
//
// Fill handling:
//   - Buy: create new TaxLot, increase position, deduct cash
//   - Sell: consume lots FIFO, decrease position, add cash, record realised P&L
//   - Partial fills: only process the filled quantity
//
// Mark-to-market:
//   - Update market_price for each position from close prices
//   - Recompute market_value, unrealised_pnl, weights
//

class PortfolioState {
public:
    explicit PortfolioState(double initial_cash);
    ~PortfolioState() = default;

    // Non-copyable, movable
    PortfolioState(const PortfolioState&) = delete;
    PortfolioState& operator=(const PortfolioState&) = delete;
    PortfolioState(PortfolioState&&) = default;
    PortfolioState& operator=(PortfolioState&&) = default;

    // -----------------------------------------------------------------------
    // T+1 Sellability
    // -----------------------------------------------------------------------

    // Shares that can be sold today (lots with sellable_date <= today).
    Volume sellable_qty(const Symbol& symbol, Date today) const;

    // Shares that cannot be sold today (lots with sellable_date > today).
    Volume unsellable_qty(const Symbol& symbol, Date today) const;

    // Total quantity held (sellable + unsellable).
    Volume total_qty(const Symbol& symbol) const;

    // Roll sellability to a new date. In the current design, sellability is
    // computed on-the-fly from TaxLot::sellable_date, so this is a no-op.
    // Retained for interface compatibility and potential future optimisation.
    void roll_sellability(Date today);

    // -----------------------------------------------------------------------
    // Fill Processing
    // -----------------------------------------------------------------------

    // Update portfolio state on a fill. Handles both buy and sell.
    // For buys:  creates a new TaxLot, deducts cash (fill_price * qty + costs).
    // For sells: consumes lots FIFO, adds cash (fill_price * qty - costs),
    //            records realised P&L per lot.
    void update_on_fill(const OrderResult& result, Date trade_date,
                        Date next_trading_day);

    // Process a batch of fills for a single day.
    void update_on_fills(const std::vector<OrderResult>& results,
                         Date trade_date, Date next_trading_day);

    // -----------------------------------------------------------------------
    // Mark-to-Market
    // -----------------------------------------------------------------------

    // Update all position prices from a price map (symbol -> close price).
    void mark_to_market(const std::unordered_map<Symbol, double>& prices);

    // Update all position prices from a MarketSnapshot.
    void mark_to_market(const MarketSnapshot& snapshot);

    // Recompute position weights after mark-to-market.
    void compute_weights();

    // -----------------------------------------------------------------------
    // NAV and Metrics
    // -----------------------------------------------------------------------

    // Total NAV = cash + sum of position market values.
    double total_nav() const;

    // Cash balance.
    double cash() const { return cash_; }

    // Gross exposure = sum of |market_value| for all positions.
    double gross_exposure() const;

    // Net exposure = sum of market_value (always positive for long-only).
    double net_exposure() const;

    // Cash weight = cash / total_nav.
    double cash_weight() const;

    // Number of held positions (with qty > 0).
    int num_positions() const;

    // Map of symbol -> weight.
    std::unordered_map<Symbol, double> position_weights() const;

    // -----------------------------------------------------------------------
    // Position Access
    // -----------------------------------------------------------------------

    // Get position for a symbol. Returns a default Position if not held.
    const Position& position(const Symbol& symbol) const;

    // Check if a position is held.
    bool has_position(const Symbol& symbol) const;

    // All positions (including zero-quantity ones until cleanup).
    const std::unordered_map<Symbol, Position>& positions() const { return positions_; }

    // Get the FIFO lot queue for a symbol.
    const std::deque<TaxLot>& tax_lots(const Symbol& symbol) const;

    // All tax lots across all symbols.
    const std::unordered_map<Symbol, std::deque<TaxLot>>& all_tax_lots() const {
        return lots_;
    }

    // -----------------------------------------------------------------------
    // Maintenance
    // -----------------------------------------------------------------------

    // Remove positions with zero quantity (housekeeping).
    void cleanup_empty_positions();

    // Adjust cash (for dividends, interest, etc.).
    void adjust_cash(double amount);

    // Force-set cash (for testing).
    void set_cash(double cash) { cash_ = cash; }

    // Reset to initial state.
    void reset(double initial_cash);

    // -----------------------------------------------------------------------
    // Snapshot
    // -----------------------------------------------------------------------

    // Get a vector of PositionRecord for reporting.
    std::vector<PositionRecord> snapshot() const;

    // Total realised P&L across all positions.
    double total_realised_pnl() const;

    // Total unrealised P&L across all positions.
    double total_unrealised_pnl() const;

private:
    double cash_;
    std::unordered_map<Symbol, Position> positions_;
    std::unordered_map<Symbol, std::deque<TaxLot>> lots_;

    // Default empty position for const reference returns.
    static const Position kEmptyPosition;
    static const std::deque<TaxLot> kEmptyLots;

    // Internal: add a new lot from a buy fill.
    void add_lot(const Symbol& symbol, Date buy_date, Volume qty,
                 double cost_per_share, Date sellable_date);

    // Internal: consume lots FIFO for a sell fill. Returns realised P&L.
    double consume_lots_fifo(const Symbol& symbol, Volume qty);

    // Internal: recalculate aggregated Position from lots.
    void recalculate_position(const Symbol& symbol);
};

} // namespace trade
