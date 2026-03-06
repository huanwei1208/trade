#pragma once

#include "trade/backtest/backtest_engine.h"
#include "trade/backtest/portfolio_state.h"
#include "trade/backtest/slippage.h"
#include "trade/common/config.h"
#include "trade/model/bar.h"
#include "trade/model/instrument.h"

#include <memory>
#include <string>
#include <unordered_map>
#include <unordered_set>

namespace trade {

// ============================================================================
// BrokerSim: A-share broker simulator implementing IExecutionVenue
// ============================================================================
//
// Faithfully simulates China A-share market microstructure:
//
// 1. T+1 Enforcement:
//    - Shares bought on day t cannot be sold until day t+1.
//    - Uses PortfolioState::sellable_qty() to check available quantity.
//    - Sell orders exceeding sellable_qty are partially filled (sellable portion)
//      or rejected (if zero sellable).
//
// 2. Price Limit Blocking (Conservative Mode):
//    - If a stock hits limit up (close >= limit_up): buy orders are REJECTED
//      (zero fill). Rationale: limit-up stocks have no sell-side liquidity.
//    - If a stock hits limit down (close <= limit_down): sell orders are REJECTED.
//      Rationale: limit-down stocks have no buy-side liquidity.
//    - Check is based on the bar's hit_limit_up / hit_limit_down flags.
//
// 3. Suspension Handling:
//    - If a stock is suspended (TradingStatus::kSuspended), all orders for that
//      symbol are cancelled with reason "suspended".
//    - Detected from bar volume == 0 or Instrument status.
//
// 4. ST Rules:
//    - ST/*ST stocks have +-5% daily limit (Board::kST).
//    - The price limit check uses the narrower ST limit automatically.
//    - Optional: reject all ST buy orders (configurable).
//
// 5. Delisting:
//    - On the last trading day before delist_date, all positions are force-closed
//      at close price (simulating the delisting settlement).
//    - New buy orders for delisting stocks are rejected.
//
// 6. Transaction Costs:
//    - Stamp tax:     0.05% on sell amount only (国家印花税).
//    - Commission:    0.025% both ways, minimum 5 yuan per trade (券商佣金).
//    - Transfer fee:  0.001% on Shanghai stocks only (中国结算过户费).
//    - All costs are deducted from cash in PortfolioState.
//
// 7. Fill Logic:
//    - Default fill price: bar open price + slippage.
//    - For MarketOnOpen orders: fill at open + slippage.
//    - For VWAP orders: fill at bar vwap + slippage.
//    - Slippage is computed by the injected SlippageModel.
//    - Lot size: buys must be rounded down to nearest 100 shares (1 手).
//      Sells can be any quantity (odd lots allowed for sell).
//

class BrokerSim : public IExecutionVenue {
public:
    struct Config {
        // Transaction cost parameters (defaults match current A-share rules)
        double stamp_tax_rate = 0.0005;         // 0.05% sell-only
        double commission_rate = 0.00025;        // 0.025% both ways
        double commission_min_yuan = 5.0;        // Min commission per trade
        double transfer_fee_rate = 0.00001;      // 0.001% SH-only

        // Fill behavior
        bool reject_limit_up_buy = true;         // Can't buy at limit up
        bool reject_limit_down_sell = true;       // Can't sell at limit down
        bool reject_st_buy = false;              // Optionally block ST buys
        bool reject_delisting_buy = true;        // Block buying delisting stocks
        bool enforce_lot_size = true;            // Round buy qty to 100 shares
        int lot_size = 100;                      // A-share standard lot

        // Participation limit
        double max_participation_rate = 0.10;    // Max fraction of daily volume
    };

    BrokerSim(
        std::shared_ptr<PortfolioState> portfolio,
        std::shared_ptr<SlippageModel> slippage);

    BrokerSim(
        std::shared_ptr<PortfolioState> portfolio,
        std::shared_ptr<SlippageModel> slippage,
        Config config);

    BrokerSim(
        std::shared_ptr<PortfolioState> portfolio,
        std::shared_ptr<SlippageModel> slippage,
        const TradingCostConfig& cost_config);

    ~BrokerSim() override = default;

    // -----------------------------------------------------------------------
    // IExecutionVenue interface
    // -----------------------------------------------------------------------

    OrderResult execute(const Order& order, const Bar& bar) override;

    std::vector<OrderResult> execute_batch(
        const std::vector<Order>& orders,
        const MarketSnapshot& snapshot) override;

    // -----------------------------------------------------------------------
    // Instrument metadata management
    // -----------------------------------------------------------------------

    // Set instrument info (needed for market detection and board type)
    void set_instrument(const Symbol& symbol, const Instrument& inst);
    void set_instruments(const std::unordered_map<Symbol, Instrument>& instruments);

    // Mark a stock as suspended on a given date
    void set_suspended(const Symbol& symbol, Date date);

    // Register delisting date for a stock
    void set_delist_date(const Symbol& symbol, Date date);

    // -----------------------------------------------------------------------
    // Force-close for delisting
    // -----------------------------------------------------------------------

    // Check if any held positions are delisting and force-close them.
    // Called by BacktestEngine in Phase 1 (pre-open).
    // Returns OrderResults for the forced sells.
    std::vector<OrderResult> force_close_delisting(
        Date date, const MarketSnapshot& snapshot);

    // -----------------------------------------------------------------------
    // Accessors
    // -----------------------------------------------------------------------

    const Config& config() const { return config_; }
    const PortfolioState& portfolio() const { return *portfolio_; }

    // Cumulative statistics
    double total_commission() const { return total_commission_; }
    double total_stamp_tax() const { return total_stamp_tax_; }
    double total_transfer_fee() const { return total_transfer_fee_; }
    double total_slippage_cost() const { return total_slippage_cost_; }
    int total_orders_submitted() const { return total_orders_submitted_; }
    int total_orders_filled() const { return total_orders_filled_; }
    int total_orders_rejected() const { return total_orders_rejected_; }

private:
    // -----------------------------------------------------------------------
    // Pre-execution checks (return empty string if OK, else rejection reason)
    // -----------------------------------------------------------------------

    std::string check_suspension(const Order& order, const Bar& bar) const;
    std::string check_price_limits(const Order& order, const Bar& bar) const;
    std::string check_t_plus_1(const Order& order, Date trade_date) const;
    std::string check_st_restrictions(const Order& order) const;
    std::string check_delisting(const Order& order, Date trade_date) const;

    // -----------------------------------------------------------------------
    // Fill computation
    // -----------------------------------------------------------------------

    // Determine the base fill price (before slippage) based on order type and bar.
    double compute_base_fill_price(const Order& order, const Bar& bar) const;

    // Apply participation rate limit: cap order quantity based on bar volume.
    Volume apply_participation_cap(const Order& order, const Bar& bar) const;

    // Round buy quantity down to lot size.
    Volume round_to_lot(Volume qty, Side side) const;

    // Compute transaction costs for a fill.
    struct CostBreakdown {
        double commission = 0.0;
        double stamp_tax = 0.0;
        double transfer_fee = 0.0;
    };
    CostBreakdown compute_costs(
        const Symbol& symbol, Side side, Volume fill_qty, double fill_price) const;

    // Check if a symbol is a Shanghai stock (for transfer fee).
    bool is_shanghai(const Symbol& symbol) const;

    // Build a rejected OrderResult.
    OrderResult make_rejected(const Order& order, const std::string& reason) const;

    // Build a cancelled OrderResult.
    OrderResult make_cancelled(const Order& order, const std::string& reason) const;

    // -----------------------------------------------------------------------
    // State
    // -----------------------------------------------------------------------

    Config config_;
    std::shared_ptr<PortfolioState> portfolio_;
    std::shared_ptr<SlippageModel> slippage_;
    std::unordered_map<Symbol, Instrument> instruments_;
    std::unordered_map<Symbol, Date> delist_dates_;
    std::unordered_set<std::string> suspended_keys_;  // "symbol|YYYY-MM-DD"

    // Cumulative cost tracking
    double total_commission_ = 0.0;
    double total_stamp_tax_ = 0.0;
    double total_transfer_fee_ = 0.0;
    double total_slippage_cost_ = 0.0;
    int total_orders_submitted_ = 0;
    int total_orders_filled_ = 0;
    int total_orders_rejected_ = 0;
};

} // namespace trade
