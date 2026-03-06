#include "trade/decision/pre_trade_check.h"
#include "trade/backtest/backtest_engine.h"

#include <cmath>

namespace trade {

PreTradeChecker::PreTradeResult PreTradeChecker::check(
    const Order& order,
    const PortfolioState& portfolio_state,
    const MarketData& market_data) const {

    PreTradeResult result;
    result.original_qty = order.quantity;
    result.adjusted_qty = order.quantity;
    result.pass = true;

    // 1. T+1 sellability check
    if (order.is_sell()) {
        if (!check_t1_sellable(order.symbol, order.quantity, portfolio_state)) {
            result.pass = false;
            result.detail.t1_sellable = false;
            result.rejection_reason = "T+1: insufficient sellable quantity";
            result.adjusted_qty = 0;
            return result;
        }
    }

    // 2. Price limit proximity check
    int limit_status = check_price_limit(order.symbol, order.side, market_data);
    if (limit_status == 2) {
        // Reject
        result.pass = false;
        result.detail.price_limit_ok = false;
        result.rejection_reason = "approaching price limit, order rejected";
        result.adjusted_qty = 0;
        return result;
    } else if (limit_status == 1) {
        // Warn and reduce
        result.detail.price_limit_ok = true;
        result.adjusted_qty = static_cast<Volume>(
            order.quantity * config_.limit_proximity_size_factor);
        result.adjusted_qty = round_to_lot(result.adjusted_qty);
        result.warnings.push_back("approaching price limit, quantity reduced");
    }

    // 3. Suspension check
    auto inst_it = market_data.instruments.find(order.symbol);
    if (inst_it != market_data.instruments.end()) {
        if (inst_it->second.status == TradingStatus::kSuspended) {
            result.pass = false;
            result.detail.not_suspended = false;
            result.rejection_reason = "stock is suspended";
            result.adjusted_qty = 0;
            return result;
        }
    }

    // 4. Participation rate check
    auto bar_it = market_data.bars.find(order.symbol);
    if (bar_it != market_data.bars.end() && bar_it->second.close > 0) {
        Volume max_qty = max_participation_qty(
            order.symbol, bar_it->second.close, market_data);
        if (max_qty > 0 && result.adjusted_qty > max_qty) {
            result.adjusted_qty = max_qty;
            result.detail.participation_ok = true;
            result.warnings.push_back("quantity reduced to participation limit");
        }
    }

    // 5. Lot size check (buy orders must be multiples of 100)
    if (order.is_buy()) {
        Volume rounded = round_to_lot(result.adjusted_qty);
        if (rounded != result.adjusted_qty) {
            result.adjusted_qty = rounded;
            result.detail.lot_size_ok = true;
            result.warnings.push_back("quantity rounded to lot size");
        }
    }

    // 6. Minimum order value check
    if (bar_it != market_data.bars.end() && bar_it->second.close > 0) {
        double notional = result.adjusted_qty * bar_it->second.close;
        if (notional < config_.min_order_notional) {
            result.pass = false;
            result.detail.min_notional_ok = false;
            result.rejection_reason = "order below minimum notional value";
            result.adjusted_qty = 0;
            return result;
        }
    }

    // If adjusted_qty is zero after all adjustments, reject
    if (result.adjusted_qty <= 0) {
        result.pass = false;
        result.rejection_reason = "adjusted quantity is zero";
    }

    return result;
}

std::vector<PreTradeChecker::PreTradeResult> PreTradeChecker::check_batch(
    const std::vector<Order>& orders,
    const PortfolioState& portfolio_state,
    const MarketData& market_data) const {

    std::vector<PreTradeResult> results;
    results.reserve(orders.size());
    for (const auto& order : orders) {
        results.push_back(check(order, portfolio_state, market_data));
    }
    return results;
}

bool PreTradeChecker::check_t1_sellable(
    const Symbol& symbol,
    Volume sell_qty,
    const PortfolioState& state) const {

    auto it = state.sellable_qty.find(symbol);
    if (it == state.sellable_qty.end()) return false;
    return sell_qty <= it->second;
}

int PreTradeChecker::check_price_limit(
    const Symbol& symbol,
    Side side,
    const MarketData& market_data) const {

    auto bar_it = market_data.bars.find(symbol);
    if (bar_it == market_data.bars.end()) return 0;

    const auto& bar = bar_it->second;
    if (bar.prev_close <= 0.0) return 0;

    // Get limit prices
    double limit_up = 0.0, limit_down = 0.0;
    auto up_it = market_data.limit_up.find(symbol);
    auto down_it = market_data.limit_down.find(symbol);

    if (up_it != market_data.limit_up.end()) {
        limit_up = up_it->second;
    } else {
        // Compute from bar and instrument
        auto inst_it = market_data.instruments.find(symbol);
        double pct = 0.10;
        if (inst_it != market_data.instruments.end()) {
            pct = price_limit_pct(inst_it->second.board);
        }
        limit_up = bar.prev_close * (1.0 + pct);
        limit_down = bar.prev_close * (1.0 - pct);
    }

    if (down_it != market_data.limit_down.end()) {
        limit_down = down_it->second;
    }

    if (side == Side::kBuy && limit_up > 0.0) {
        double proximity = (limit_up - bar.close) / limit_up;
        if (proximity < config_.limit_proximity_reject_pct) return 2;
        if (proximity < config_.limit_proximity_warn_pct) return 1;
    }

    if (side == Side::kSell && limit_down > 0.0) {
        double proximity = (bar.close - limit_down) / limit_down;
        if (proximity < config_.limit_proximity_reject_pct) return 2;
        if (proximity < config_.limit_proximity_warn_pct) return 1;
    }

    return 0;
}

Volume PreTradeChecker::max_participation_qty(
    const Symbol& symbol,
    double price,
    const MarketData& market_data) const {

    auto adv_it = market_data.adv_20d.find(symbol);
    if (adv_it == market_data.adv_20d.end() || price <= 0.0) return 0;

    double max_value = adv_it->second * config_.max_participation;
    return static_cast<Volume>(max_value / price);
}

Volume PreTradeChecker::round_to_lot(Volume qty) const {
    return (qty / config_.lot_size) * config_.lot_size;
}

} // namespace trade
