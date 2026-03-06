#pragma once

#include "trade/backtest/backtest_engine.h"
#include "trade/common/types.h"
#include "trade/model/bar.h"

#include <cmath>
#include <memory>
#include <string>

namespace trade {

// ============================================================================
// SlippageModel: base class for slippage estimation
// ============================================================================
//
// Slippage is the difference between the theoretical fill price and the actual
// fill price due to market impact, spread, and execution delay.
//
// Convention:
//   - Slippage is always expressed as a POSITIVE fraction of base price.
//   - For buys:  actual_fill = base_price * (1 + slippage)
//   - For sells: actual_fill = base_price * (1 - slippage)
//
// All models return slippage as a non-negative double (fractional, not bps).
//

class SlippageModel {
public:
    virtual ~SlippageModel() = default;

    // Compute slippage fraction for a given order and bar.
    // Returns a non-negative fraction (e.g., 0.0005 = 5 bps).
    virtual double compute(const Order& order, const Bar& bar) const = 0;

    // Apply slippage to a base price.
    // Buys: price goes up. Sells: price goes down.
    double apply(double base_price, Side side, const Order& order,
                 const Bar& bar) const {
        double slip = compute(order, bar);
        if (side == Side::kBuy) {
            return base_price * (1.0 + slip);
        } else {
            return base_price * (1.0 - slip);
        }
    }

    // Model name for logging / configuration.
    virtual std::string name() const = 0;
};

// ============================================================================
// FixedSlippage: fixed basis points by market-cap bucket
// ============================================================================
//
// Simple, conservative model suitable for initial research.
// Slippage depends on the stock's approximate market-cap bucket:
//   - Large cap  (top 300 by market cap):   5 bps  (0.05%)
//   - Mid cap    (300-800):                12 bps  (0.12%)
//   - Small cap  (800+):                   25 bps  (0.25%)
//
// The bucket is determined by daily turnover amount (proxy for liquidity):
//   - amount > 500M yuan  → large
//   - amount > 100M yuan  → mid
//   - otherwise           → small
//

enum class MarketCapBucket : uint8_t {
    kLarge = 0,
    kMid   = 1,
    kSmall = 2,
};

class FixedSlippage : public SlippageModel {
public:
    struct Config {
        double large_cap_bps = 5.0;      // bps for large cap
        double mid_cap_bps   = 12.0;     // bps for mid cap
        double small_cap_bps = 25.0;     // bps for small cap

        // Turnover thresholds for bucket classification (yuan)
        double large_cap_amount_threshold = 500'000'000.0;   // 5亿
        double mid_cap_amount_threshold   = 100'000'000.0;   // 1亿
    };

    FixedSlippage();
    explicit FixedSlippage(Config config);

    double compute(const Order& order, const Bar& bar) const override;

    std::string name() const override { return "FixedSlippage"; }

    // Classify a bar into a market-cap bucket.
    MarketCapBucket classify(const Bar& bar) const;

    const Config& config() const { return config_; }

private:
    Config config_;
};

// ============================================================================
// ParticipationSlippage: square-root market impact model
// ============================================================================
//
// Slippage = a * sqrt(participation_rate) * volatility
//
// Where:
//   participation_rate = order_qty / bar_volume
//   volatility         = bar amplitude (high - low) / prev_close
//   a                  = impact coefficient (calibrated, default 0.5)
//
// This model captures the empirical observation that market impact scales
// with the square root of order size relative to daily volume, modulated
// by intraday volatility.
//
// Reference: Almgren et al. (2005), "Direct estimation of equity market impact"
//

class ParticipationSlippage : public SlippageModel {
public:
    struct Config {
        double impact_coefficient = 0.5;  // a: calibrated impact coefficient
        double min_slippage_bps = 1.0;    // Floor: at least 1 bp
        double max_slippage_bps = 100.0;  // Cap: at most 100 bps (1%)
    };

    ParticipationSlippage();
    explicit ParticipationSlippage(Config config);

    double compute(const Order& order, const Bar& bar) const override;

    std::string name() const override { return "ParticipationSlippage"; }

    const Config& config() const { return config_; }

private:
    Config config_;
};

// ============================================================================
// AlmgrenChrissSlippage: temporary + permanent market impact model
// ============================================================================
//
// Based on Almgren & Chriss (2000) optimal execution framework.
//
// Total impact = temporary_impact + permanent_impact
//
// Temporary impact (reverts after execution):
//   temp = eta * sigma * (order_qty / (ADV * T))^0.6
//
// Permanent impact (shifts the price level):
//   perm = gamma * sigma * (order_qty / ADV)
//
// Where:
//   sigma = daily volatility (annualised / sqrt(252))
//   ADV   = average daily volume in shares
//   T     = execution horizon in days (default 1 for single-day)
//   eta   = temporary impact coefficient (calibrated)
//   gamma = permanent impact coefficient (calibrated)
//
// Calibration: coefficients are historically calibrated per market
// (A-share specific values differ from US equity defaults).
//

class AlmgrenChrissSlippage : public SlippageModel {
public:
    struct Config {
        double eta = 0.142;           // Temporary impact coefficient
        double gamma = 0.314;         // Permanent impact coefficient
        double temp_exponent = 0.6;   // Exponent for temporary impact
        double daily_vol = 0.025;     // Default daily volatility if not computed
        double default_adv = 1'000'000; // Default ADV in shares if unknown
        double execution_horizon = 1.0; // Execution horizon in days
        double min_slippage_bps = 1.0;
        double max_slippage_bps = 200.0;
    };

    AlmgrenChrissSlippage();
    explicit AlmgrenChrissSlippage(Config config);

    double compute(const Order& order, const Bar& bar) const override;

    std::string name() const override { return "AlmgrenChrissSlippage"; }

    // Set ADV for a symbol (for more accurate impact estimation).
    void set_adv(const Symbol& symbol, double adv_shares);

    // Set realised daily volatility for a symbol.
    void set_volatility(const Symbol& symbol, double daily_vol);

    const Config& config() const { return config_; }

private:
    Config config_;
    std::unordered_map<Symbol, double> adv_map_;
    std::unordered_map<Symbol, double> vol_map_;

    double get_adv(const Symbol& symbol) const;
    double get_volatility(const Symbol& symbol) const;
};

// ============================================================================
// SlippageFactory: create slippage models by research phase
// ============================================================================
//
// Phase convention:
//   - Research:        FixedSlippage (simple, conservative baseline)
//   - Pre-production:  ParticipationSlippage (more realistic)
//   - Production:      AlmgrenChrissSlippage (full calibrated model)
//

enum class ResearchPhase : uint8_t {
    kResearch       = 0,
    kPreProduction  = 1,
    kProduction     = 2,
};

class SlippageFactory {
public:
    // Create a slippage model appropriate for the given research phase.
    static std::unique_ptr<SlippageModel> create(ResearchPhase phase);

    // Create by name: "fixed", "participation", "almgren_chriss".
    static std::unique_ptr<SlippageModel> create(const std::string& name);
};

} // namespace trade
