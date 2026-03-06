#include "trade/backtest/portfolio_state.h"

#include <algorithm>
#include <cmath>

namespace trade {

const Position PortfolioState::kEmptyPosition = {};
const std::deque<TaxLot> PortfolioState::kEmptyLots = {};

PortfolioState::PortfolioState(double initial_cash) : cash_(initial_cash) {}

// ---------------------------------------------------------------------------
// T+1 Sellability
// ---------------------------------------------------------------------------

Volume PortfolioState::sellable_qty(const Symbol& symbol, Date today) const {
    auto it = lots_.find(symbol);
    if (it == lots_.end()) return 0;
    Volume qty = 0;
    for (const auto& lot : it->second) {
        if (lot.is_sellable(today)) qty += lot.quantity;
    }
    return qty;
}

Volume PortfolioState::unsellable_qty(const Symbol& symbol, Date today) const {
    return total_qty(symbol) - sellable_qty(symbol, today);
}

Volume PortfolioState::total_qty(const Symbol& symbol) const {
    auto it = positions_.find(symbol);
    if (it == positions_.end()) return 0;
    return it->second.total_qty;
}

void PortfolioState::roll_sellability(Date /*today*/) {
    // No-op: sellability is computed on-the-fly from TaxLot::sellable_date.
    // Retained for interface compatibility.
}

// ---------------------------------------------------------------------------
// Fill Processing
// ---------------------------------------------------------------------------

void PortfolioState::update_on_fill(const OrderResult& result,
                                     Date trade_date,
                                     Date next_trading_day) {
    if (!result.is_filled()) return;

    const auto& symbol = result.order.symbol;
    double fill_amount = result.fill_price * static_cast<double>(result.fill_qty);
    double total_costs = result.total_cost();

    if (result.order.side == Side::kBuy) {
        // ---------------------------------------------------------------
        // BUY: create new TaxLot, deduct cash, update position
        // ---------------------------------------------------------------

        // Cost per share includes prorated commission / fees
        double cost_per_share = (fill_amount + total_costs)
                                / static_cast<double>(result.fill_qty);

        // Create a new tax lot; sellable on next_trading_day (T+1)
        add_lot(symbol, trade_date, result.fill_qty,
                cost_per_share, next_trading_day);

        // Deduct cash: pay for shares + all transaction costs
        cash_ -= (fill_amount + total_costs);

        // Recalculate aggregated position from lots
        recalculate_position(symbol);

    } else {
        // ---------------------------------------------------------------
        // SELL: consume lots FIFO, add cash, record realised P&L
        // ---------------------------------------------------------------

        // consume_lots_fifo returns the total cost basis of consumed lots
        double cost_basis_consumed = consume_lots_fifo(symbol, result.fill_qty);

        // Cash received: sell proceeds minus transaction costs
        cash_ += (fill_amount - total_costs);

        // Realised P&L = sell proceeds - cost basis - transaction costs
        double realised_pnl = fill_amount - cost_basis_consumed - total_costs;

        // Accumulate realised P&L on the position
        auto& pos = positions_[symbol];
        pos.realised_pnl += realised_pnl;

        // Recalculate aggregated position from lots
        recalculate_position(symbol);
    }
}

void PortfolioState::update_on_fills(const std::vector<OrderResult>& results,
                                      Date trade_date,
                                      Date next_trading_day) {
    for (const auto& r : results) {
        if (r.is_filled()) {
            update_on_fill(r, trade_date, next_trading_day);
        }
    }
}

// ---------------------------------------------------------------------------
// Mark-to-Market
// ---------------------------------------------------------------------------

void PortfolioState::mark_to_market(
    const std::unordered_map<Symbol, double>& prices) {
    for (auto& [sym, pos] : positions_) {
        if (pos.total_qty == 0) continue;
        auto pit = prices.find(sym);
        if (pit != prices.end()) {
            pos.market_price = pit->second;
        }
        // Recompute derived fields
        pos.market_value = pos.market_price
                           * static_cast<double>(pos.total_qty);
        pos.unrealised_pnl = pos.market_value - pos.total_cost_basis;
    }
}

void PortfolioState::mark_to_market(const MarketSnapshot& snapshot) {
    for (auto& [sym, pos] : positions_) {
        if (pos.total_qty == 0) continue;
        if (snapshot.has(sym)) {
            pos.market_price = snapshot.bar(sym).close;
        }
        pos.market_value = pos.market_price
                           * static_cast<double>(pos.total_qty);
        pos.unrealised_pnl = pos.market_value - pos.total_cost_basis;
    }
}

void PortfolioState::compute_weights() {
    double nav = total_nav();
    if (nav <= 0.0) return;
    for (auto& [sym, pos] : positions_) {
        pos.weight = pos.market_value / nav;
    }
}

// ---------------------------------------------------------------------------
// NAV and Metrics
// ---------------------------------------------------------------------------

double PortfolioState::total_nav() const {
    double nav = cash_;
    for (const auto& [sym, pos] : positions_) {
        nav += pos.market_value;
    }
    return nav;
}

double PortfolioState::gross_exposure() const {
    double exp = 0.0;
    for (const auto& [sym, pos] : positions_) {
        exp += std::abs(pos.market_value);
    }
    return exp;
}

double PortfolioState::net_exposure() const {
    double exp = 0.0;
    for (const auto& [sym, pos] : positions_) {
        exp += pos.market_value;
    }
    return exp;
}

double PortfolioState::cash_weight() const {
    double nav = total_nav();
    return nav > 0.0 ? cash_ / nav : 1.0;
}

int PortfolioState::num_positions() const {
    int count = 0;
    for (const auto& [sym, pos] : positions_) {
        if (pos.total_qty > 0) ++count;
    }
    return count;
}

std::unordered_map<Symbol, double> PortfolioState::position_weights() const {
    std::unordered_map<Symbol, double> weights;
    for (const auto& [sym, pos] : positions_) {
        if (pos.total_qty > 0) weights[sym] = pos.weight;
    }
    return weights;
}

// ---------------------------------------------------------------------------
// Position Access
// ---------------------------------------------------------------------------

const Position& PortfolioState::position(const Symbol& symbol) const {
    auto it = positions_.find(symbol);
    if (it != positions_.end()) return it->second;
    return kEmptyPosition;
}

bool PortfolioState::has_position(const Symbol& symbol) const {
    auto it = positions_.find(symbol);
    return it != positions_.end() && it->second.total_qty > 0;
}

const std::deque<TaxLot>& PortfolioState::tax_lots(const Symbol& symbol) const {
    auto it = lots_.find(symbol);
    if (it != lots_.end()) return it->second;
    return kEmptyLots;
}

// ---------------------------------------------------------------------------
// Maintenance
// ---------------------------------------------------------------------------

void PortfolioState::cleanup_empty_positions() {
    for (auto it = positions_.begin(); it != positions_.end();) {
        if (it->second.total_qty == 0) {
            lots_.erase(it->first);
            it = positions_.erase(it);
        } else {
            ++it;
        }
    }
}

void PortfolioState::adjust_cash(double amount) {
    cash_ += amount;
}

void PortfolioState::reset(double initial_cash) {
    cash_ = initial_cash;
    positions_.clear();
    lots_.clear();
}

// ---------------------------------------------------------------------------
// Snapshot
// ---------------------------------------------------------------------------

std::vector<PositionRecord> PortfolioState::snapshot() const {
    std::vector<PositionRecord> records;
    for (const auto& [sym, pos] : positions_) {
        if (pos.total_qty > 0) {
            PositionRecord r;
            r.symbol = sym;
            r.quantity = pos.total_qty;
            r.market_value = pos.market_value;
            r.weight = pos.weight;
            r.unrealised_pnl = pos.unrealised_pnl;
            r.cost_basis = pos.total_cost_basis;
            records.push_back(r);
        }
    }
    return records;
}

double PortfolioState::total_realised_pnl() const {
    double pnl = 0.0;
    for (const auto& [sym, pos] : positions_) pnl += pos.realised_pnl;
    return pnl;
}

double PortfolioState::total_unrealised_pnl() const {
    double pnl = 0.0;
    for (const auto& [sym, pos] : positions_) pnl += pos.unrealised_pnl;
    return pnl;
}

// ---------------------------------------------------------------------------
// Internal: lot management
// ---------------------------------------------------------------------------

void PortfolioState::add_lot(const Symbol& symbol, Date buy_date,
                              Volume qty, double cost_per_share,
                              Date sellable_date) {
    TaxLot lot;
    lot.buy_date = buy_date;
    lot.quantity = qty;
    lot.cost_price = cost_per_share;
    lot.sellable_date = sellable_date;
    lots_[symbol].push_back(lot);
}

double PortfolioState::consume_lots_fifo(const Symbol& symbol, Volume qty) {
    auto it = lots_.find(symbol);
    if (it == lots_.end()) return 0.0;

    auto& lot_queue = it->second;
    Volume remaining = qty;
    double total_cost_basis = 0.0;

    // Consume lots in FIFO order
    while (remaining > 0 && !lot_queue.empty()) {
        auto& front = lot_queue.front();
        Volume consume = std::min(remaining, front.quantity);

        // Accumulate cost basis for realised P&L calculation
        total_cost_basis += front.cost_price * static_cast<double>(consume);

        front.quantity -= consume;
        remaining -= consume;

        // Remove exhausted lots
        if (front.quantity == 0) {
            lot_queue.pop_front();
        }
    }

    [[maybe_unused]] Volume actually_consumed = qty - remaining;

    // Realised P&L: we compute it as difference between the market value
    // (at the fill price the caller will use) and the cost basis.
    // However, we don't know the fill price here. The caller (update_on_fill)
    // knows the fill price, so we return the cost basis consumed and let
    // the caller compute the actual P&L.
    //
    // Actually, we return: (fill_price is not available here)
    // We return the negative of cost_basis so caller can add fill_amount.
    // Convention: return value = fill_price * consumed - cost_basis
    // But since we don't have fill_price, we'll return -cost_basis and
    // the caller adds fill_amount.
    //
    // Wait -- let's simplify. Return the total cost basis consumed.
    // Caller computes: realised_pnl = fill_amount - cost_basis_consumed - costs
    return total_cost_basis;
}

void PortfolioState::recalculate_position(const Symbol& symbol) {
    auto& pos = positions_[symbol];
    pos.symbol = symbol;

    // Preserve realised_pnl across recalculations
    double saved_realised_pnl = pos.realised_pnl;

    auto lot_it = lots_.find(symbol);
    if (lot_it == lots_.end() || lot_it->second.empty()) {
        // No lots remaining
        pos.total_qty = 0;
        pos.avg_cost = 0.0;
        pos.total_cost_basis = 0.0;
        pos.market_value = 0.0;
        pos.unrealised_pnl = 0.0;
        pos.realised_pnl = saved_realised_pnl;
        return;
    }

    const auto& lots = lot_it->second;
    Volume total = 0;
    double total_cost = 0.0;

    for (const auto& lot : lots) {
        total += lot.quantity;
        total_cost += lot.total_cost();
    }

    pos.total_qty = total;
    pos.total_cost_basis = total_cost;
    pos.avg_cost = (total > 0) ? total_cost / static_cast<double>(total) : 0.0;

    // market_value and unrealised_pnl use the last known market_price.
    // They will be updated properly during mark_to_market.
    pos.market_value = pos.market_price * static_cast<double>(pos.total_qty);
    pos.unrealised_pnl = pos.market_value - pos.total_cost_basis;
    pos.realised_pnl = saved_realised_pnl;
}

} // namespace trade
