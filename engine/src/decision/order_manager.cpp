#include "trade/decision/order_manager.h"
#include "trade/backtest/backtest_engine.h"

#include <algorithm>
#include <cmath>

namespace trade {

OrderManager::ExecutionPlan OrderManager::create_execution_plan(
    const std::vector<Order>& orders,
    const std::unordered_map<Symbol, double>& adv_20d,
    const std::unordered_map<Symbol, double>& volatility,
    const std::unordered_map<Symbol, VolumeProfile>& volume_profiles) const {

    ExecutionPlan plan;
    plan.total_parent_orders = static_cast<int>(orders.size());

    for (const auto& order : orders) {
        double adv = 0.0;
        auto adv_it = adv_20d.find(order.symbol);
        if (adv_it != adv_20d.end()) adv = adv_it->second;

        double vol = 0.0;
        auto vol_it = volatility.find(order.symbol);
        if (vol_it != volatility.end()) vol = vol_it->second;

        VolumeProfile profile;
        auto prof_it = volume_profiles.find(order.symbol);
        if (prof_it != volume_profiles.end()) {
            profile = prof_it->second;
        } else {
            profile = default_profile();
        }

        // Derive price from available data:
        // 1. Use the order's limit_price if explicitly set (> 0).
        // 2. Otherwise estimate from ADV (yuan) / estimated daily volume (shares).
        // 3. Fall back to 1.0 if no data is available (notional will be
        //    recalculated once real market data is obtained before execution).
        double price = 0.0;
        if (order.limit_price > 0.0) {
            price = order.limit_price;
        } else if (adv > 0.0 && prof_it != volume_profiles.end()
                   && profile.estimated_daily_volume > 0) {
            price = adv / static_cast<double>(profile.estimated_daily_volume);
        } else if (adv > 0.0 && order.quantity > 0) {
            // Rough estimate: assume order is ~target_participation of daily volume,
            // so daily_volume ~ order.quantity / target_participation, and
            // price ~ adv / daily_volume.
            double est_daily_vol = static_cast<double>(order.quantity)
                                   / std::max(config_.target_participation, 0.01);
            price = adv / std::max(est_daily_vol, 1.0);
        }
        if (price <= 0.0) {
            price = 1.0;  // Safe fallback; plan will be re-priced before execution
        }
        auto children = split_order(order, price, adv, vol, profile);
        plan.child_orders.insert(plan.child_orders.end(),
                                 children.begin(), children.end());
    }

    plan.total_child_orders = static_cast<int>(plan.child_orders.size());

    // Compute sessions needed
    int max_session = 0;
    for (const auto& child : plan.child_orders) {
        max_session = std::max(max_session, child.session_day);
    }
    plan.sessions_needed = max_session + 1;

    // Build per-session summaries
    plan.sessions.resize(plan.sessions_needed);
    for (int s = 0; s < plan.sessions_needed; ++s) {
        plan.sessions[s].session_day = s;
    }
    for (const auto& child : plan.child_orders) {
        auto& session = plan.sessions[child.session_day];
        session.num_child_orders++;
        plan.total_estimated_slippage_bps += child.estimated_slippage_bps;
    }

    if (plan.total_child_orders > 0) {
        plan.total_estimated_slippage_bps /= plan.total_child_orders;
    }

    return plan;
}

double OrderManager::estimate_slippage_bps(
    double participation,
    double volatility,
    double urgency) const {

    double adj_participation = participation * (1.0 + (urgency - 0.5) * config_.urgency_multiplier);
    double slip = config_.slippage_spread_bps
                + config_.slippage_impact_a * std::pow(adj_participation, config_.slippage_impact_exp)
                + config_.slippage_vol_b * volatility;
    return std::max(0.0, slip);
}

double OrderManager::estimate_execution_cost(
    double notional,
    double slippage_bps,
    bool is_sell) {

    double commission_bps = 2.5;  // 万2.5
    double stamp_tax_bps = is_sell ? 5.0 : 0.0;  // 千0.5 for sell only
    double total_bps = slippage_bps + commission_bps + stamp_tax_bps;
    return notional * total_bps / 10000.0;
}

bool OrderManager::is_large_order(
    double order_notional,
    double adv_20d) const {

    if (adv_20d <= 0.0) return false;
    return order_notional / adv_20d > config_.large_order_adv_pct;
}

std::vector<OrderManager::ChildOrder> OrderManager::split_order(
    const Order& order,
    double price,
    double adv_20d,
    double volatility,
    const VolumeProfile& profile) const {

    std::vector<ChildOrder> children;

    double notional = static_cast<double>(order.quantity) * price;
    int sessions = sessions_for_order(notional, adv_20d);
    int slices = num_slices();
    if (slices <= 0) slices = 1;

    // Distribute quantity across sessions and time slices
    Volume remaining = order.quantity;
    Volume per_session = order.quantity / std::max(sessions, 1);

    for (int s = 0; s < sessions && remaining > 0; ++s) {
        Volume session_qty = (s == sessions - 1) ? remaining : per_session;
        Volume slice_remaining = session_qty;

        for (int t = 0; t < slices && slice_remaining > 0; ++t) {
            double fraction = 1.0 / static_cast<double>(slices);
            if (!profile.bucket_fractions.empty() && t < static_cast<int>(profile.bucket_fractions.size())) {
                fraction = profile.bucket_fractions[t];
            }

            Volume slice_qty = static_cast<Volume>(session_qty * fraction);
            // Round to lot size (100 shares)
            slice_qty = (slice_qty / 100) * 100;
            if (slice_qty == 0 && slice_remaining > 0) slice_qty = 100;
            slice_qty = std::min(slice_qty, slice_remaining);

            ChildOrder child;
            child.symbol = order.symbol;
            child.side = order.side;
            child.quantity = slice_qty;
            child.session_day = s;
            child.start_minute = config_.main_window_start_min
                                + t * config_.slice_interval_minutes;
            child.end_minute = child.start_minute + config_.slice_interval_minutes;
            child.participation_target = config_.target_participation;
            child.estimated_slippage_bps = estimate_slippage_bps(
                config_.target_participation, volatility, order.urgency);
            child.parent_reason = order.reason;

            children.push_back(child);
            slice_remaining -= slice_qty;
        }

        remaining -= session_qty;
    }

    return children;
}

int OrderManager::sessions_for_order(
    double order_notional,
    double adv_20d) const {

    if (adv_20d <= 0.0) return 1;
    if (!is_large_order(order_notional, adv_20d)) return 1;

    double ratio = order_notional / adv_20d;
    int sessions = static_cast<int>(std::ceil(ratio / config_.large_order_adv_pct));
    return std::min(sessions, config_.large_order_max_sessions);
}

int OrderManager::main_window_minutes() const {
    return config_.main_window_end_min - config_.main_window_start_min;
}

int OrderManager::num_slices() const {
    int window = main_window_minutes();
    if (config_.slice_interval_minutes <= 0) return 1;
    return std::max(1, window / config_.slice_interval_minutes);
}

OrderManager::VolumeProfile OrderManager::default_profile() const {
    // Flat profile: equal volume in each bucket
    VolumeProfile profile;
    int slices = num_slices();
    if (slices > 0) {
        profile.bucket_fractions.resize(slices, 1.0 / static_cast<double>(slices));
    }
    profile.estimated_daily_volume = 0;
    return profile;
}

} // namespace trade
