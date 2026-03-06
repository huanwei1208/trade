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
// LiquidityCalculator  (Priority P2 -- Liquidity)
// ============================================================================
//
// Features computed:
//
// --- Turnover ---
//   turnover_rate_5d        mean turnover rate over 5 days
//   turnover_rate_20d       mean turnover rate over 20 days
//   delta_turnover_5d       turnover_rate_5d / turnover_rate_20d - 1
//                           (turnover surge/decline indicator)
//   turnover_rate_5d_cs_rank  cross-sectional rank
//   delta_turnover_5d_cs_rank cross-sectional rank
//
// --- Amihud illiquidity ---
//   amihud_20d              mean(|return| / volume_yuan, 20d)  * 1e8
//   amihud_60d              mean(|return| / volume_yuan, 60d)  * 1e8
//   amihud_20d_cs_rank      cross-sectional rank
//
// --- Volume ratio ---
//   volume_ratio_20d        volume / MA(volume, 20d)
//   volume_ratio_20d_cs_rank  cross-sectional rank
//
// --- VWAP deviation ---
//   vwap_dev                (close / VWAP - 1)
//   vwap_dev_cs_rank        cross-sectional rank
//
// --- Time-series z-score variants ---
//   turnover_rate_5d_ts_z   ts_zscore(turnover_rate_5d, 60)
//   delta_turnover_5d_ts_z  ts_zscore(delta_turnover_5d, 60)
//   amihud_20d_ts_z         ts_zscore(amihud_20d, 120)
//   volume_ratio_20d_ts_z   ts_zscore(volume_ratio_20d, 60)
//   vwap_dev_ts_z           ts_zscore(vwap_dev, 60)
//
class LiquidityCalculator : public FeatureCalculator {
public:
    std::string group_name() const override { return "liquidity"; }

    FeatureSet compute(
        const std::vector<BarSeries>& series,
        const std::unordered_map<Symbol, Instrument>& instruments) const override;

    // --- Individual factor helpers (static for unit-testing) ---------------

    // Rolling mean turnover rate
    static Eigen::VectorXd rolling_turnover(
        const Eigen::VectorXd& turnover_rates, int window);

    // Delta turnover: short_window / long_window - 1
    // Positive values indicate a recent surge in trading activity.
    static Eigen::VectorXd delta_turnover(
        const Eigen::VectorXd& turnover_rates,
        int short_window, int long_window);

    // Amihud illiquidity measure: mean(|ret| / volume_yuan) * scale_factor
    // Higher values indicate less liquid stocks.
    // |daily_returns| and |volumes_yuan| must have the same length.
    static Eigen::VectorXd amihud_illiquidity(
        const Eigen::VectorXd& daily_returns,
        const Eigen::VectorXd& volumes_yuan,
        int window,
        double scale = 1e8);

    // Volume ratio: current volume / MA(volume, window)
    // Values > 1 indicate above-average volume.
    static Eigen::VectorXd volume_ratio(
        const Eigen::VectorXd& volumes, int window);

    // VWAP deviation: close / VWAP - 1
    // Positive: close above VWAP (buying pressure).
    // Negative: close below VWAP (selling pressure).
    static Eigen::VectorXd vwap_deviation(
        const Eigen::VectorXd& closes,
        const Eigen::VectorXd& vwaps);

private:
    // Extract field vectors from BarSeries
    static Eigen::VectorXd extract_turnover_rates(const BarSeries& bs);
    static Eigen::VectorXd extract_daily_returns(const BarSeries& bs);
    static Eigen::VectorXd extract_amounts(const BarSeries& bs);
    static Eigen::VectorXd extract_volumes(const BarSeries& bs);
    static Eigen::VectorXd extract_closes(const BarSeries& bs);
    static Eigen::VectorXd extract_vwaps(const BarSeries& bs);
};

} // namespace trade
