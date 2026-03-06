#pragma once

#include "trade/features/feature_engine.h"
#include "trade/model/bar.h"
#include "trade/model/instrument.h"

#include <Eigen/Dense>
#include <string>
#include <unordered_map>
#include <vector>

namespace trade {

// ============================================================================
// SmartMoneyCalculator  (Group G -- Smart Money / Chaikin Flow)
// ============================================================================
//
// Derives smart-money accumulation / distribution signals from OHLCV data
// using the Chaikin Money Flow (CMF) framework.  No optional Bar fields are
// required — the signals are computed entirely from open, high, low, close,
// volume, and amount.
//
// Chaikin Money Flow formula:
//   MFM  = ((close - low) - (high - close)) / (high - low)  ∈ [-1, +1]
//   MFV  = MFM × volume
//   CMF(n) = sum(MFV, n) / sum(volume, n)
//
// A positive CMF indicates accumulation (smart money buying);
// a negative CMF indicates distribution (smart money selling).
//
// Features computed (2 features):
//   smart_money_flow_5d       5-day Chaikin Money Flow
//   smart_money_flow_20d      20-day Chaikin Money Flow
//
class SmartMoneyCalculator : public FeatureCalculator {
public:
    SmartMoneyCalculator() = default;

    std::string group_name() const override { return "smart_money"; }

    FeatureSet compute(
        const std::vector<BarSeries>& series,
        const std::unordered_map<Symbol, Instrument>& instruments) const override;

    // --- Individual helpers (static for unit-testing) ----------------------

    // Money Flow Multiplier: ((close-low)-(high-close))/(high-low), element-wise.
    // Returns NaN where high == low (zero-range bar).
    static Eigen::VectorXd money_flow_multiplier(
        const Eigen::VectorXd& high,
        const Eigen::VectorXd& low,
        const Eigen::VectorXd& close);

    // Chaikin Money Flow over a rolling window.
    // mfm: money_flow_multiplier, vol: daily volume.
    static Eigen::VectorXd chaikin_money_flow(
        const Eigen::VectorXd& mfm,
        const Eigen::VectorXd& vol,
        int window);
};

} // namespace trade
