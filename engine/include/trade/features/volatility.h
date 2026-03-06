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
// VolatilityCalculator  (Priority P1 -- Volatility)
// ============================================================================
//
// Features computed:
//
// --- Realized volatility ---
//   realized_vol_20d        std(daily_returns, 20d)
//   realized_vol_60d        std(daily_returns, 60d)
//   realized_vol_20d_cs_rank  cross-sectional rank
//   realized_vol_60d_cs_rank  cross-sectional rank
//
// --- High-low amplitude ---
//   hilo_amp_20d            mean((high-low)/close, 20d)
//   hilo_amp_60d            mean((high-low)/close, 60d)
//   hilo_amp_20d_cs_rank    cross-sectional rank
//
// --- Volatility of volatility ---
//   vol_of_vol_20d          std(realized_vol_20d, 20d rolling)
//   vol_of_vol_20d_cs_rank  cross-sectional rank
//
// --- Idiosyncratic volatility ---
//   idio_vol_20d            std(regression residual vs market, 20d)
//   idio_vol_60d            std(regression residual vs market, 60d)
//   idio_vol_20d_cs_rank    cross-sectional rank
//
// --- Time-series z-score variants ---
//   realized_vol_20d_ts_z   ts_zscore(realized_vol_20d, 120)
//   realized_vol_60d_ts_z   ts_zscore(realized_vol_60d, 240)
//   hilo_amp_20d_ts_z       ts_zscore(hilo_amp_20d, 120)
//   vol_of_vol_20d_ts_z     ts_zscore(vol_of_vol_20d, 120)
//
class VolatilityCalculator : public FeatureCalculator {
public:
    std::string group_name() const override { return "volatility"; }

    FeatureSet compute(
        const std::vector<BarSeries>& series,
        const std::unordered_map<Symbol, Instrument>& instruments) const override;

    // --- Individual factor helpers (static for unit-testing) ---------------

    // Realized volatility: rolling std of daily returns.
    // Output length == input length; first (window-1) entries are NaN.
    static Eigen::VectorXd realized_volatility(
        const Eigen::VectorXd& daily_returns, int window);

    // High-low amplitude: rolling mean of (high - low) / close.
    // |highs|, |lows|, |closes| must have the same length.
    static Eigen::VectorXd high_low_amplitude(
        const Eigen::VectorXd& highs,
        const Eigen::VectorXd& lows,
        const Eigen::VectorXd& closes,
        int window);

    // Volatility of volatility: rolling std of a volatility series.
    static Eigen::VectorXd vol_of_vol(
        const Eigen::VectorXd& vol_series, int window);

    // Idiosyncratic volatility: std of residuals from CAPM regression.
    //   r_stock = alpha + beta * r_market + epsilon
    //   output  = rolling_std(epsilon, window)
    static Eigen::VectorXd idiosyncratic_volatility(
        const Eigen::VectorXd& stock_returns,
        const Eigen::VectorXd& market_returns,
        int window);

private:
    // Extract daily return series from bars
    static Eigen::VectorXd extract_daily_returns(const BarSeries& bs);

    // Extract high, low, close price series from bars
    static void extract_hlc(const BarSeries& bs,
                            Eigen::VectorXd& highs,
                            Eigen::VectorXd& lows,
                            Eigen::VectorXd& closes);

    // Compute equal-weighted market return from all series
    static Eigen::VectorXd compute_market_return(
        const std::vector<BarSeries>& series, int max_len);
};

} // namespace trade
