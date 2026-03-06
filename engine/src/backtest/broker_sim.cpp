#include "trade/backtest/broker_sim.h"
#include "trade/common/time_utils.h"

#include <algorithm>
#include <cmath>
#include <sstream>

namespace trade {

// ---------------------------------------------------------------------------
// Constructors
// ---------------------------------------------------------------------------

BrokerSim::BrokerSim(
    std::shared_ptr<PortfolioState> portfolio,
    std::shared_ptr<SlippageModel> slippage)
    : config_{}
    , portfolio_(std::move(portfolio))
    , slippage_(std::move(slippage)) {}

BrokerSim::BrokerSim(
    std::shared_ptr<PortfolioState> portfolio,
    std::shared_ptr<SlippageModel> slippage,
    Config config)
    : config_(std::move(config))
    , portfolio_(std::move(portfolio))
    , slippage_(std::move(slippage)) {}

BrokerSim::BrokerSim(
    std::shared_ptr<PortfolioState> portfolio,
    std::shared_ptr<SlippageModel> slippage,
    const TradingCostConfig& cost_config)
    : portfolio_(std::move(portfolio))
    , slippage_(std::move(slippage)) {
    config_.stamp_tax_rate = cost_config.stamp_tax_rate;
    config_.commission_rate = cost_config.commission_rate;
    config_.commission_min_yuan = cost_config.commission_min_yuan;
    config_.transfer_fee_rate = cost_config.transfer_fee_rate;
}

// ---------------------------------------------------------------------------
// IExecutionVenue interface
// ---------------------------------------------------------------------------

OrderResult BrokerSim::execute(const Order& order, const Bar& bar) {
    ++total_orders_submitted_;

    // -----------------------------------------------------------------------
    // Step 1: Pre-execution checks (rejection pipeline)
    // -----------------------------------------------------------------------

    // Check suspension
    std::string reason = check_suspension(order, bar);
    if (!reason.empty()) {
        ++total_orders_rejected_;
        return make_cancelled(order, reason);
    }

    // Check price limits
    reason = check_price_limits(order, bar);
    if (!reason.empty()) {
        ++total_orders_rejected_;
        return make_rejected(order, reason);
    }

    // Check ST restrictions
    reason = check_st_restrictions(order);
    if (!reason.empty()) {
        ++total_orders_rejected_;
        return make_rejected(order, reason);
    }

    // Check delisting
    reason = check_delisting(order, bar.date);
    if (!reason.empty()) {
        ++total_orders_rejected_;
        return make_rejected(order, reason);
    }

    // Check T+1 for sell orders
    reason = check_t_plus_1(order, bar.date);
    if (!reason.empty()) {
        ++total_orders_rejected_;
        return make_rejected(order, reason);
    }

    // -----------------------------------------------------------------------
    // Step 2: Determine fill quantity
    // -----------------------------------------------------------------------

    Volume order_qty = order.quantity;

    // For sell orders, cap at sellable quantity (T+1 enforcement)
    if (order.side == Side::kSell) {
        Volume sellable = portfolio_->sellable_qty(order.symbol, bar.date);
        order_qty = std::min(order_qty, sellable);
        if (order_qty <= 0) {
            ++total_orders_rejected_;
            return make_rejected(order, "no sellable shares (T+1)");
        }
    }

    // Apply participation rate cap (max fraction of daily volume)
    Volume capped_qty = apply_participation_cap(
        Order{order.symbol, order.side, order_qty, order.order_type,
              order.limit_price, order.urgency, order.reason},
        bar);

    if (capped_qty <= 0) {
        ++total_orders_rejected_;
        return make_rejected(order, "zero volume after participation cap");
    }

    // Round buy orders to lot size
    Volume fill_qty = round_to_lot(capped_qty, order.side);
    if (fill_qty <= 0) {
        ++total_orders_rejected_;
        return make_rejected(order, "quantity below minimum lot size");
    }

    // -----------------------------------------------------------------------
    // Step 3: Determine fill price
    // -----------------------------------------------------------------------

    double base_price = compute_base_fill_price(order, bar);

    // Apply slippage model
    double fill_price = slippage_->apply(base_price, order.side, order, bar);

    // Clamp fill price within the day's high-low range
    fill_price = std::max(bar.low, std::min(bar.high, fill_price));

    // For limit orders, check if fill price is acceptable
    if (order.order_type == OrderType::kLimitOnOpen) {
        if (order.side == Side::kBuy && fill_price > order.limit_price) {
            ++total_orders_rejected_;
            return make_rejected(order, "limit price exceeded (buy)");
        }
        if (order.side == Side::kSell && fill_price < order.limit_price) {
            ++total_orders_rejected_;
            return make_rejected(order, "limit price not met (sell)");
        }
    }

    // -----------------------------------------------------------------------
    // Step 4: Compute transaction costs
    // -----------------------------------------------------------------------

    CostBreakdown costs = compute_costs(order.symbol, order.side,
                                         fill_qty, fill_price);

    // Check if we have enough cash for a buy
    if (order.side == Side::kBuy) {
        double required_cash = fill_price * static_cast<double>(fill_qty)
                               + costs.commission + costs.transfer_fee;
        if (required_cash > portfolio_->cash()) {
            // Try to reduce quantity to fit cash
            double available = portfolio_->cash();
            double price_per_share = fill_price
                + (costs.commission + costs.transfer_fee)
                  / static_cast<double>(fill_qty);
            Volume affordable = static_cast<Volume>(available / price_per_share);
            affordable = round_to_lot(affordable, Side::kBuy);

            if (affordable <= 0) {
                ++total_orders_rejected_;
                return make_rejected(order, "insufficient cash");
            }
            fill_qty = affordable;
            costs = compute_costs(order.symbol, order.side, fill_qty, fill_price);
        }
    }

    // -----------------------------------------------------------------------
    // Step 5: Build result
    // -----------------------------------------------------------------------

    double slippage_cost = std::abs(fill_price - base_price)
                           * static_cast<double>(fill_qty);

    OrderResult result;
    result.order = order;
    result.fill_price = fill_price;
    result.fill_qty = fill_qty;
    result.commission = costs.commission;
    result.stamp_tax = costs.stamp_tax;
    result.transfer_fee = costs.transfer_fee;
    result.slippage_cost = slippage_cost;

    // Determine fill status
    if (fill_qty == order.quantity) {
        result.status = FillStatus::kFilled;
    } else {
        result.status = FillStatus::kPartialFill;
    }

    // Update cumulative statistics
    ++total_orders_filled_;
    total_commission_ += costs.commission;
    total_stamp_tax_ += costs.stamp_tax;
    total_transfer_fee_ += costs.transfer_fee;
    total_slippage_cost_ += slippage_cost;

    return result;
}

std::vector<OrderResult> BrokerSim::execute_batch(
    const std::vector<Order>& orders,
    const MarketSnapshot& snapshot) {
    std::vector<OrderResult> results;
    results.reserve(orders.size());
    for (const auto& order : orders) {
        if (snapshot.has(order.symbol)) {
            results.push_back(execute(order, snapshot.bar(order.symbol)));
        } else {
            ++total_orders_submitted_;
            ++total_orders_rejected_;
            results.push_back(make_cancelled(order, "no market data"));
        }
    }
    return results;
}

// ---------------------------------------------------------------------------
// Instrument metadata management
// ---------------------------------------------------------------------------

void BrokerSim::set_instrument(const Symbol& symbol, const Instrument& inst) {
    instruments_[symbol] = inst;
}

void BrokerSim::set_instruments(
    const std::unordered_map<Symbol, Instrument>& instruments) {
    instruments_ = instruments;
}

void BrokerSim::set_suspended(const Symbol& symbol, Date date) {
    // Build a key "symbol|YYYY-MM-DD" for quick lookup
    suspended_keys_.insert(symbol + "|" + format_date(date));
}

void BrokerSim::set_delist_date(const Symbol& symbol, Date date) {
    delist_dates_[symbol] = date;
}

// ---------------------------------------------------------------------------
// Force-close for delisting
// ---------------------------------------------------------------------------

std::vector<OrderResult> BrokerSim::force_close_delisting(
    Date date, const MarketSnapshot& snapshot) {
    std::vector<OrderResult> results;

    for (const auto& [sym, delist_date] : delist_dates_) {
        // Check if delisting is tomorrow (force-close on last trading day)
        if (!portfolio_->has_position(sym)) continue;

        // Delist on the date itself or the day before
        // We force-close if today is the last day before delisting
        if (date >= delist_date) continue;  // Already past delist date

        // Check if next trading day is at or past delist date
        // Simple heuristic: if delist_date - date <= 1 calendar day, close
        auto days_until = (delist_date - date).count();
        if (days_until > 3) continue;  // Not close to delisting yet

        if (!snapshot.has(sym)) continue;

        const auto& bar = snapshot.bar(sym);
        Volume pos_qty = portfolio_->total_qty(sym);
        if (pos_qty <= 0) continue;

        // Create a forced sell order
        Order sell_order;
        sell_order.symbol = sym;
        sell_order.side = Side::kSell;
        sell_order.quantity = pos_qty;
        sell_order.order_type = OrderType::kMarketOnOpen;
        sell_order.reason = "forced_delisting_close";

        // Execute at close price with costs but without T+1 check
        // (regulatory exception for delisting)
        double fill_price = bar.close;
        CostBreakdown costs = compute_costs(sym, Side::kSell, pos_qty,
                                             fill_price);

        OrderResult result;
        result.order = sell_order;
        result.status = FillStatus::kFilled;
        result.fill_price = fill_price;
        result.fill_qty = pos_qty;
        result.commission = costs.commission;
        result.stamp_tax = costs.stamp_tax;
        result.transfer_fee = costs.transfer_fee;
        result.slippage_cost = 0.0;

        total_commission_ += costs.commission;
        total_stamp_tax_ += costs.stamp_tax;
        total_transfer_fee_ += costs.transfer_fee;
        ++total_orders_filled_;

        results.push_back(result);
    }

    return results;
}

// ---------------------------------------------------------------------------
// Pre-execution checks
// ---------------------------------------------------------------------------

std::string BrokerSim::check_suspension(const Order& order,
                                         const Bar& bar) const {
    // Check 1: Bar volume is zero (suspended)
    if (bar.volume == 0) {
        return "suspended (zero volume)";
    }

    // Check 2: Explicit suspension set
    std::string key = order.symbol + "|" + format_date(bar.date);
    if (suspended_keys_.count(key) > 0) {
        return "suspended";
    }

    // Check 3: Instrument status
    auto inst_it = instruments_.find(order.symbol);
    if (inst_it != instruments_.end()) {
        if (inst_it->second.status == TradingStatus::kSuspended) {
            return "suspended (instrument status)";
        }
    }

    return "";
}

std::string BrokerSim::check_price_limits(const Order& order,
                                           const Bar& bar) const {
    // Determine the board type for this symbol
    Board board = Board::kMain;
    auto inst_it = instruments_.find(order.symbol);
    if (inst_it != instruments_.end()) {
        board = inst_it->second.board;
        // ST stocks use kST board for limit purposes
        if (inst_it->second.is_st()) {
            board = Board::kST;
        }
    }

    // Compute limit prices from prev_close and board
    double pct = price_limit_pct(board);
    double limit_up = bar.prev_close * (1.0 + pct);
    double limit_down = bar.prev_close * (1.0 - pct);

    // Round to tick size (0.01)
    limit_up = static_cast<int>(limit_up * 100 + 0.5) / 100.0;
    limit_down = static_cast<int>(limit_down * 100 + 0.5) / 100.0;

    // Check if stock hit limit up: close >= limit_up - small tolerance
    bool at_limit_up = (bar.close >= limit_up - 0.005);
    // Check if stock hit limit down: close <= limit_down + small tolerance
    bool at_limit_down = (bar.close <= limit_down + 0.005);

    // At limit up: can sell but cannot buy
    if (at_limit_up && config_.reject_limit_up_buy && order.side == Side::kBuy) {
        return "limit up - no buy-side liquidity";
    }

    // At limit down: can buy but cannot sell
    if (at_limit_down && config_.reject_limit_down_sell && order.side == Side::kSell) {
        return "limit down - no sell-side liquidity";
    }

    return "";
}

std::string BrokerSim::check_t_plus_1(const Order& order,
                                       Date trade_date) const {
    if (order.side != Side::kSell) return "";

    Volume sellable = portfolio_->sellable_qty(order.symbol, trade_date);
    if (sellable <= 0) {
        return "T+1: no sellable shares";
    }

    // We don't reject here for partial sells -- that's handled in execute()
    // by capping the quantity. This check only rejects if there are zero
    // sellable shares.
    return "";
}

std::string BrokerSim::check_st_restrictions(const Order& order) const {
    if (!config_.reject_st_buy) return "";
    if (order.side != Side::kBuy) return "";

    auto inst_it = instruments_.find(order.symbol);
    if (inst_it != instruments_.end() && inst_it->second.is_st()) {
        return "ST stock - buy rejected by policy";
    }

    return "";
}

std::string BrokerSim::check_delisting(const Order& order,
                                        Date trade_date) const {
    if (!config_.reject_delisting_buy) return "";
    if (order.side != Side::kBuy) return "";

    auto it = delist_dates_.find(order.symbol);
    if (it != delist_dates_.end()) {
        // Reject buys if within delisting period
        auto days_until = (it->second - trade_date).count();
        if (days_until <= 30) {  // Within 30 calendar days of delisting
            return "delisting - buy rejected";
        }
    }

    // Also check instrument status
    auto inst_it = instruments_.find(order.symbol);
    if (inst_it != instruments_.end()) {
        if (inst_it->second.status == TradingStatus::kDelisting) {
            return "delisting - buy rejected";
        }
    }

    return "";
}

// ---------------------------------------------------------------------------
// Fill computation
// ---------------------------------------------------------------------------

double BrokerSim::compute_base_fill_price(const Order& order,
                                           const Bar& bar) const {
    switch (order.order_type) {
        case OrderType::kMarketOnOpen:
            return bar.open;

        case OrderType::kLimitOnOpen:
            // For limit orders, the fill price is the better of open and limit
            if (order.side == Side::kBuy) {
                return std::min(bar.open, order.limit_price);
            } else {
                return std::max(bar.open, order.limit_price);
            }

        case OrderType::kVWAP:
            // Use bar VWAP if available, otherwise approximate
            if (bar.vwap > 0.0) {
                return bar.vwap;
            }
            // Fallback: approximate VWAP as (open + high + low + close) / 4
            return (bar.open + bar.high + bar.low + bar.close) / 4.0;

        case OrderType::kTWAP:
            // Approximate TWAP as midpoint of open and close
            return (bar.open + bar.close) / 2.0;
    }

    return bar.open;
}

Volume BrokerSim::apply_participation_cap(const Order& order,
                                           const Bar& bar) const {
    if (bar.volume <= 0) return 0;

    double max_qty = config_.max_participation_rate
                     * static_cast<double>(bar.volume);
    Volume capped = std::min(order.quantity,
                             static_cast<Volume>(max_qty));
    return std::max(capped, static_cast<Volume>(0));
}

Volume BrokerSim::round_to_lot(Volume qty, Side side) const {
    if (side == Side::kBuy && config_.enforce_lot_size) {
        return (qty / config_.lot_size) * config_.lot_size;
    }
    // Sells: odd lots are allowed in A-share market
    return qty;
}

BrokerSim::CostBreakdown BrokerSim::compute_costs(
    const Symbol& symbol, Side side, Volume fill_qty,
    double fill_price) const {
    CostBreakdown costs;
    double amount = fill_price * static_cast<double>(fill_qty);

    // Commission: both ways, minimum 5 yuan per trade
    costs.commission = std::max(config_.commission_min_yuan,
                                amount * config_.commission_rate);

    // Stamp tax: 0.05% on sell amount only
    if (side == Side::kSell) {
        costs.stamp_tax = amount * config_.stamp_tax_rate;
    }

    // Transfer fee: 0.001% on Shanghai stocks only
    if (is_shanghai(symbol)) {
        costs.transfer_fee = amount * config_.transfer_fee_rate;
    }

    return costs;
}

bool BrokerSim::is_shanghai(const Symbol& symbol) const {
    // Check for ".SH" suffix
    if (symbol.size() >= 3) {
        return symbol.substr(symbol.size() - 2) == "SH";
    }
    // Also check by stock code prefix: 6xxxxx are Shanghai
    if (symbol.size() >= 1 && symbol[0] == '6') {
        return true;
    }
    return false;
}

OrderResult BrokerSim::make_rejected(const Order& order,
                                      const std::string& reason) const {
    OrderResult r;
    r.order = order;
    r.status = FillStatus::kRejected;
    r.reject_reason = reason;
    return r;
}

OrderResult BrokerSim::make_cancelled(const Order& order,
                                       const std::string& reason) const {
    OrderResult r;
    r.order = order;
    r.status = FillStatus::kCancelled;
    r.reject_reason = reason;
    return r;
}

} // namespace trade
