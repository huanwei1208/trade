#include "trade/backtest/slippage.h"

#include <algorithm>
#include <cmath>
#include <unordered_map>

namespace trade {

// ---------------------------------------------------------------------------
// Constructors
// ---------------------------------------------------------------------------

FixedSlippage::FixedSlippage() : config_{} {}
FixedSlippage::FixedSlippage(Config config) : config_(config) {}

ParticipationSlippage::ParticipationSlippage() : config_{} {}
ParticipationSlippage::ParticipationSlippage(Config config) : config_(config) {}

AlmgrenChrissSlippage::AlmgrenChrissSlippage() : config_{} {}
AlmgrenChrissSlippage::AlmgrenChrissSlippage(Config config) : config_(config) {}

// ============================================================================
// FixedSlippage: fixed basis points by market-cap bucket
// ============================================================================
//
// Slippage depends on the stock's approximate market-cap bucket, determined
// by daily turnover amount (proxy for liquidity):
//   - Large cap  (amount > 500M):   5 bps  (0.05%)
//   - Mid cap    (amount > 100M):  12 bps  (0.12%)
//   - Small cap  (otherwise):      25 bps  (0.25%)
//

double FixedSlippage::compute(const Order& /*order*/, const Bar& bar) const {
    auto bucket = classify(bar);
    switch (bucket) {
        case MarketCapBucket::kLarge:
            return config_.large_cap_bps / 10000.0;
        case MarketCapBucket::kMid:
            return config_.mid_cap_bps / 10000.0;
        case MarketCapBucket::kSmall:
            return config_.small_cap_bps / 10000.0;
    }
    return config_.small_cap_bps / 10000.0;
}

MarketCapBucket FixedSlippage::classify(const Bar& bar) const {
    if (bar.amount >= config_.large_cap_amount_threshold)
        return MarketCapBucket::kLarge;
    if (bar.amount >= config_.mid_cap_amount_threshold)
        return MarketCapBucket::kMid;
    return MarketCapBucket::kSmall;
}

// ============================================================================
// ParticipationSlippage: square-root market impact model
// ============================================================================
//
// Slippage = a * sqrt(participation_rate) * volatility
//
// Where:
//   participation_rate = order_qty / bar_volume
//   volatility         = bar amplitude (high - low) / close
//   a                  = impact coefficient (calibrated, default 0.5)
//
// The result is clamped between min_slippage_bps and max_slippage_bps.
//

double ParticipationSlippage::compute(const Order& order,
                                       const Bar& bar) const {
    // If zero volume, return minimum slippage (avoid division by zero)
    if (bar.volume == 0) {
        return config_.min_slippage_bps / 10000.0;
    }

    // Participation rate: fraction of daily volume
    double participation = static_cast<double>(order.quantity)
                         / static_cast<double>(bar.volume);

    // Intraday volatility proxy: amplitude = (high - low) / close
    // Use prev_close as the normalizer for consistency with the paper
    double reference_price = bar.prev_close > 0 ? bar.prev_close : bar.close;
    double volatility = 0.0;
    if (reference_price > 0.0 && bar.high > 0.0) {
        volatility = (bar.high - bar.low) / reference_price;
    }

    // Impact = a * sqrt(participation) * volatility
    double slip_bps = config_.impact_coefficient
                    * std::sqrt(participation)
                    * volatility
                    * 10000.0;

    // Urgency multiplier: more urgent orders have higher impact
    // Scale from 0.8 (patient) to 1.5 (aggressive) based on urgency
    double urgency_mult = 0.8 + 0.7 * order.urgency;
    slip_bps *= urgency_mult;

    // Clamp to configured bounds
    slip_bps = std::max(config_.min_slippage_bps,
                        std::min(config_.max_slippage_bps, slip_bps));

    return slip_bps / 10000.0;
}

// ============================================================================
// AlmgrenChrissSlippage: temporary + permanent market impact model
// ============================================================================
//
// Based on Almgren & Chriss (2000) optimal execution framework.
//
// Total impact = temporary_impact + permanent_impact
//
// Temporary impact (reverts after execution):
//   temp = eta * sigma * (order_qty / (ADV * T))^temp_exponent
//
// Permanent impact (shifts the price level):
//   perm = gamma * sigma * (order_qty / ADV)
//
// Parameters:
//   sigma = daily volatility (from vol_map_ or default)
//   ADV   = average daily volume in shares (from adv_map_ or default)
//   T     = execution horizon in days (default 1)
//   eta   = temporary impact coefficient (default 0.142)
//   gamma = permanent impact coefficient (default 0.314)
//

double AlmgrenChrissSlippage::compute(const Order& order,
                                       const Bar& /*bar*/) const {
    double adv = get_adv(order.symbol);
    double sigma = get_volatility(order.symbol);
    double qty = static_cast<double>(order.quantity);

    // Guard against division by zero
    if (adv <= 0.0 || config_.execution_horizon <= 0.0) {
        return config_.min_slippage_bps / 10000.0;
    }

    // Participation rate for temporary impact: qty / (ADV * T)
    double participation = qty / (adv * config_.execution_horizon);

    // Temporary impact: eta * sigma * participation^temp_exponent
    double temp_impact = config_.eta * sigma
                       * std::pow(std::max(participation, 0.0),
                                  config_.temp_exponent);

    // Permanent impact: gamma * sigma * (qty / ADV)
    double perm_impact = config_.gamma * sigma * (qty / adv);

    // Total impact in fractional terms
    double total_impact = temp_impact + perm_impact;

    // Convert to bps
    double total_bps = total_impact * 10000.0;

    // Urgency scaling: more aggressive execution increases temporary impact
    double urgency_mult = 0.7 + 0.6 * order.urgency;
    total_bps *= urgency_mult;

    // Clamp to configured bounds
    total_bps = std::max(config_.min_slippage_bps,
                         std::min(config_.max_slippage_bps, total_bps));

    return total_bps / 10000.0;
}

void AlmgrenChrissSlippage::set_adv(const Symbol& symbol, double adv_shares) {
    adv_map_[symbol] = adv_shares;
}

void AlmgrenChrissSlippage::set_volatility(const Symbol& symbol,
                                            double daily_vol) {
    vol_map_[symbol] = daily_vol;
}

double AlmgrenChrissSlippage::get_adv(const Symbol& symbol) const {
    auto it = adv_map_.find(symbol);
    return it != adv_map_.end() ? it->second : config_.default_adv;
}

double AlmgrenChrissSlippage::get_volatility(const Symbol& symbol) const {
    auto it = vol_map_.find(symbol);
    return it != vol_map_.end() ? it->second : config_.daily_vol;
}

// ============================================================================
// SlippageFactory: create slippage models by research phase or name
// ============================================================================

std::unique_ptr<SlippageModel> SlippageFactory::create(ResearchPhase phase) {
    switch (phase) {
        case ResearchPhase::kResearch:
            return std::make_unique<FixedSlippage>();
        case ResearchPhase::kPreProduction:
            return std::make_unique<ParticipationSlippage>();
        case ResearchPhase::kProduction:
            return std::make_unique<AlmgrenChrissSlippage>();
    }
    return std::make_unique<FixedSlippage>();
}

std::unique_ptr<SlippageModel> SlippageFactory::create(const std::string& name) {
    if (name == "fixed") return std::make_unique<FixedSlippage>();
    if (name == "participation") return std::make_unique<ParticipationSlippage>();
    if (name == "almgren_chriss") return std::make_unique<AlmgrenChrissSlippage>();
    // Default to fixed slippage
    return std::make_unique<FixedSlippage>();
}

} // namespace trade
