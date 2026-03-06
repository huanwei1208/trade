#pragma once

#include "trade/common/types.h"
#include "trade/model/bar.h"

#include <string>
#include <unordered_map>
#include <vector>

namespace trade {

// Forward declaration
struct Order;

// ============================================================================
// OrderManager: intelligent order splitting and execution scheduling
// ============================================================================
//
// Converts high-level portfolio trade instructions into a sequence of timed
// child orders suitable for execution via VWAP/TWAP hybrid algorithms.
//
// Design principles:
//   - Trading window: avoid first 10-15 minutes of the session; main window
//     is 10:00 - 14:30 (with optional mop-up from 14:30 - 14:55).
//   - VWAP/TWAP hybrid: split parent orders into sub-orders at 5-15 minute
//     intervals, targeting a participation rate <= 8-12% of interval volume.
//   - Large orders (> 5% of 20d ADV): spread across multiple trading sessions
//     to minimise market impact.
//   - Slippage model:
//       slippage_bps = spread_bps + a * participation^0.6 + b * volatility
//     where a, b are empirically calibrated constants.
//
class OrderManager {
public:
    // -----------------------------------------------------------------------
    // Configuration
    // -----------------------------------------------------------------------
    struct Config {
        // Trading window (minutes from market open 09:30)
        int avoid_open_minutes = 15;             // skip first 15 min
        int main_window_start_min = 30;          // 10:00 (09:30 + 30 min)
        int main_window_end_min = 300;           // 14:30 (09:30 + 5h, minus lunch)
        int mopup_end_min = 325;                 // 14:55

        // Sub-order splitting
        int slice_interval_minutes = 10;         // interval between child orders
        double target_participation = 0.10;      // target % of interval volume
        double max_participation = 0.12;         // hard cap on participation

        // Large order threshold
        double large_order_adv_pct = 0.05;       // > 5% of 20d ADV = large
        int large_order_max_sessions = 3;        // spread across up to 3 sessions

        // Slippage model coefficients
        //   slippage_bps = spread_bps + a * participation^0.6 + b * volatility
        double slippage_spread_bps = 3.0;        // estimated half-spread
        double slippage_impact_a = 15.0;         // participation impact coeff
        double slippage_impact_exp = 0.6;        // participation exponent
        double slippage_vol_b = 5.0;             // volatility multiplier

        // Urgency adjustment: multiplier on participation for urgent orders
        double urgency_multiplier = 1.5;         // at urgency=1.0
    };

    // -----------------------------------------------------------------------
    // Child order: a single time-sliced sub-order
    // -----------------------------------------------------------------------
    struct ChildOrder {
        Symbol symbol;
        Side side = Side::kBuy;
        Volume quantity = 0;                     // shares to execute in this slice
        int session_day = 0;                     // 0 = today, 1 = tomorrow, etc.
        int start_minute = 0;                    // minutes from market open (09:30)
        int end_minute = 0;                      // end of execution window
        double participation_target = 0.0;       // target % of interval volume
        double estimated_slippage_bps = 0.0;     // expected slippage for this slice
        std::string parent_reason;               // inherited from parent order
    };

    // -----------------------------------------------------------------------
    // Execution plan: complete schedule for a set of parent orders
    // -----------------------------------------------------------------------
    struct ExecutionPlan {
        std::vector<ChildOrder> child_orders;    // all child orders across sessions

        // Summary statistics
        int total_parent_orders = 0;
        int total_child_orders = 0;
        int sessions_needed = 0;                 // number of trading sessions used
        double total_estimated_slippage_bps = 0.0; // weighted average slippage
        double total_estimated_cost_yuan = 0.0;  // total estimated execution cost

        // Per-session breakdown
        struct SessionSummary {
            int session_day = 0;                 // 0 = today, 1 = tomorrow
            int num_child_orders = 0;
            double notional_value = 0.0;         // total notional for this session
            double estimated_slippage_bps = 0.0;
        };
        std::vector<SessionSummary> sessions;

        // Check if the plan contains any orders
        bool empty() const { return child_orders.empty(); }
        size_t size() const { return child_orders.size(); }
    };

    // -----------------------------------------------------------------------
    // Volume profile: intraday volume distribution for VWAP targeting
    // -----------------------------------------------------------------------
    struct VolumeProfile {
        // Volume fraction per time bucket (sums to ~1.0).
        // Buckets are aligned to slice_interval_minutes.
        // Index 0 = first bucket after open, etc.
        std::vector<double> bucket_fractions;

        // Estimated total daily volume (shares) for the symbol
        Volume estimated_daily_volume = 0;
    };

    OrderManager() : config_{} {}
    explicit OrderManager(Config cfg) : config_(std::move(cfg)) {}

    // -----------------------------------------------------------------------
    // Core interface
    // -----------------------------------------------------------------------

    // Create an execution plan for a set of parent orders.
    //   orders:         parent-level orders (from portfolio optimizer)
    //   adv_20d:        20-day average daily volume per symbol (yuan)
    //   volatility:     annualised volatility per symbol
    //   volume_profiles: optional intraday volume profiles per symbol
    // Returns: an ExecutionPlan with timed child orders.
    ExecutionPlan create_execution_plan(
        const std::vector<Order>& orders,
        const std::unordered_map<Symbol, double>& adv_20d,
        const std::unordered_map<Symbol, double>& volatility,
        const std::unordered_map<Symbol, VolumeProfile>& volume_profiles = {}) const;

    // -----------------------------------------------------------------------
    // Slippage estimation
    // -----------------------------------------------------------------------

    // Estimate slippage in basis points for a given participation rate and vol.
    //   participation: fraction of interval volume (e.g. 0.10)
    //   volatility:    annualised stock volatility
    //   urgency:       order urgency [0, 1]
    double estimate_slippage_bps(
        double participation,
        double volatility,
        double urgency = 0.5) const;

    // Estimate total execution cost (slippage + commissions) in yuan.
    //   notional:      order notional value
    //   slippage_bps:  estimated slippage from estimate_slippage_bps()
    //   is_sell:       true if sell (adds stamp tax)
    static double estimate_execution_cost(
        double notional,
        double slippage_bps,
        bool is_sell);

    // -----------------------------------------------------------------------
    // Order splitting logic
    // -----------------------------------------------------------------------

    // Determine if an order qualifies as "large" (> threshold % of ADV).
    bool is_large_order(
        double order_notional,
        double adv_20d) const;

    // Split a single parent order into child orders.
    std::vector<ChildOrder> split_order(
        const Order& order,
        double price,
        double adv_20d,
        double volatility,
        const VolumeProfile& profile) const;
    std::vector<ChildOrder> split_order(
        const Order& order,
        double price,
        double adv_20d,
        double volatility) const {
        return split_order(order, price, adv_20d, volatility, VolumeProfile{});
    }

    // Compute the number of sessions needed for a large order.
    int sessions_for_order(
        double order_notional,
        double adv_20d) const;

    const Config& config() const { return config_; }
    void set_config(const Config& cfg) { config_ = cfg; }

private:
    Config config_;

    // Number of trading minutes in the main window (excluding lunch break)
    int main_window_minutes() const;

    // Number of time slices in the main window
    int num_slices() const;

    // Generate a default flat volume profile if none is provided
    VolumeProfile default_profile() const;
};

} // namespace trade
