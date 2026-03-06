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
// MomentumCalculator  (Priority P1 -- Momentum / Reversal)
// ============================================================================
//
// Features computed:
//
// --- Cross-sectional reversal ---
//   ret_5d              cumulative 5-day return
//   ret_20d             cumulative 20-day return
//   ret_5d_cs_rank      rank(-ret_5d)    short-term reversal signal
//   ret_20d_cs_rank     rank(-ret_20d)   medium-short reversal signal
//
// --- Cross-sectional momentum ---
//   ret_60d             cumulative 60-day return
//   ret_120d            cumulative 120-day return
//   ret_60d_cs_rank     rank(ret_60d)    medium-term momentum
//   ret_120d_cs_rank    rank(ret_120d)   long-term momentum
//
// --- Idiosyncratic momentum ---
//   idio_vol_20d        std of daily idiosyncratic returns over 20d
//   idio_vol_60d        std of daily idiosyncratic returns over 60d
//
// --- Time-series z-score variants ---
//   ret_5d_ts_z         ts_zscore(ret_5d, 60)
//   ret_20d_ts_z        ts_zscore(ret_20d, 120)
//   ret_60d_ts_z        ts_zscore(ret_60d, 240)
//   ret_120d_ts_z       ts_zscore(ret_120d, 240)
//
class MomentumCalculator : public FeatureCalculator {
public:
    std::string group_name() const override { return "momentum"; }

    FeatureSet compute(
        const std::vector<BarSeries>& series,
        const std::unordered_map<Symbol, Instrument>& instruments) const override;

    // --- Individual factor helpers (static for unit-testing) ---------------

    // Cumulative return over [t-window, t]: prod(1+r_i) - 1
    static Eigen::VectorXd cumulative_return(
        const Eigen::VectorXd& daily_returns, int window);

    // Idiosyncratic volatility: std of residuals from regression of stock
    // returns on market returns over the given window.
    //   r_stock = alpha + beta * r_market + epsilon
    //   idio_vol = std(epsilon)
    static Eigen::VectorXd idiosyncratic_volatility(
        const Eigen::VectorXd& stock_returns,
        const Eigen::VectorXd& market_returns,
        int window);

    // Cross-sectional rank of -return (reversal) for one date slice.
    // Input:  vector of returns for N stocks at a single date.
    // Output: fractional rank of -ret in [0, 1].
    static Eigen::VectorXd reversal_rank(const Eigen::VectorXd& returns);

    // Cross-sectional rank of +return (momentum) for one date slice.
    static Eigen::VectorXd momentum_rank(const Eigen::VectorXd& returns);

private:
    // Extract daily return series from bars: (close[t]/close[t-1] - 1)
    static Eigen::VectorXd extract_daily_returns(const BarSeries& bs);

    // Compute equal-weighted market return from all series
    static Eigen::VectorXd compute_market_return(
        const std::vector<BarSeries>& series, int max_len);
};

} // namespace trade
