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
// FundFlowCalculator  (Priority P3 -- Fund Flow)
// ============================================================================
//
// These factors capture institutional and leveraged capital dynamics that
// are specific to the A-share market.  They use optional Bar fields
// (north_net_buy, margin_balance, short_sell_volume) and an estimate of
// float market-cap.
//
// Features computed:
//
// --- Northbound (HK Connect) capital ---
//   north_net_buy_5d            sum of northbound net buy over 5d (wan yuan)
//   north_net_buy_20d           sum of northbound net buy over 20d
//   north_chg_rate_5d           north_net_buy_5d / float_mktcap
//   north_chg_rate_5d_cs_rank   cross-sectional rank
//   north_chg_rate_5d_ts_z      ts_zscore(north_chg_rate_5d, 60)
//
// --- Margin (leveraged long) ---
//   margin_to_float             margin_balance / float_mktcap
//   margin_chg_5d               (margin_balance - margin_balance_5d_ago) /
//                               margin_balance_5d_ago
//   margin_chg_20d              (margin_balance - margin_balance_20d_ago) /
//                               margin_balance_20d_ago
//   margin_to_float_cs_rank     cross-sectional rank
//   margin_chg_5d_cs_rank       cross-sectional rank
//   margin_chg_20d_cs_rank      cross-sectional rank
//   margin_to_float_ts_z        ts_zscore(margin_to_float, 120)
//   margin_chg_5d_ts_z          ts_zscore(margin_chg_5d, 60)
//
// --- Short selling ---
//   short_sell_ratio             short_sell_volume / total_volume
//   short_sell_ratio_cs_rank     cross-sectional rank
//   short_sell_ratio_ts_z        ts_zscore(short_sell_ratio, 60)
//
// NOTE: When Bar optional fields are missing, the corresponding feature
//       values are set to NaN (handled by the preprocessor pipeline).
//
class FundFlowCalculator : public FeatureCalculator {
public:
    // Float market-cap data keyed by (symbol, date).  Must be supplied
    // externally (not available in Bar).
    struct FloatMktCap {
        std::unordered_map<Symbol, Eigen::VectorXd> data;  // per-stock time series
    };

    explicit FundFlowCalculator(FloatMktCap float_mktcap = {});

    std::string group_name() const override { return "fund_flow"; }

    FeatureSet compute(
        const std::vector<BarSeries>& series,
        const std::unordered_map<Symbol, Instrument>& instruments) const override;

    // --- Individual factor helpers (static for unit-testing) ---------------

    // Rolling sum of northbound net buy
    static Eigen::VectorXd north_net_buy_sum(
        const Eigen::VectorXd& daily_north, int window);

    // Change rate of northbound relative to float market cap
    static Eigen::VectorXd north_change_rate(
        const Eigen::VectorXd& daily_north,
        const Eigen::VectorXd& float_mktcap,
        int window);

    // Margin balance / float market cap
    static Eigen::VectorXd margin_to_float(
        const Eigen::VectorXd& margin_balance,
        const Eigen::VectorXd& float_mktcap);

    // Margin balance change rate over window
    static Eigen::VectorXd margin_change(
        const Eigen::VectorXd& margin_balance, int window);

    // Short sell volume / total volume
    static Eigen::VectorXd short_sell_ratio(
        const Eigen::VectorXd& short_volume,
        const Eigen::VectorXd& total_volume);

private:
    FloatMktCap float_mktcap_;

    // Extract optional Bar fields, returning NaN where unavailable
    static Eigen::VectorXd extract_north_net_buy(const BarSeries& bs);
    static Eigen::VectorXd extract_margin_balance(const BarSeries& bs);
    static Eigen::VectorXd extract_short_sell_volume(const BarSeries& bs);
    static Eigen::VectorXd extract_total_volume(const BarSeries& bs);
};

} // namespace trade
