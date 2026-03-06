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
// IndustryStyleCalculator  (Priority P5 -- Industry / Style)
// ============================================================================
//
// Factors that capture industry relative dynamics and market-cap style
// effects.  These are essential for industry-neutral portfolio construction
// and for detecting sector rotation.
//
// Features computed:
//
// --- Industry relative strength ---
//   ind_rel_strength_5d       stock_ret_5d  - industry_median_ret_5d
//   ind_rel_strength_20d      stock_ret_20d - industry_median_ret_20d
//   ind_rel_strength_5d_cs_rank   cross-sectional rank
//   ind_rel_strength_20d_cs_rank  cross-sectional rank
//   ind_rel_strength_5d_ts_z      ts_zscore(ind_rel_strength_5d, 60)
//   ind_rel_strength_20d_ts_z     ts_zscore(ind_rel_strength_20d, 120)
//
// --- Industry momentum ---
//   ind_mom_20d               equal-weighted industry return over 20d
//   ind_mom_60d               equal-weighted industry return over 60d
//   ind_mom_20d_cs_rank       cross-sectional rank (across industries)
//   ind_mom_60d_cs_rank       cross-sectional rank (across industries)
//
// --- Market-cap group ---
//   log_mktcap                log(market_cap)
//   mktcap_quantile           quantile bucket of log(mktcap) within date
//                             0 = smallest, 4 = largest (quintiles)
//   log_mktcap_cs_rank        cross-sectional rank
//
class IndustryStyleCalculator : public FeatureCalculator {
public:
    // Market-cap data keyed by symbol (daily series aligned with bars).
    struct MktCapData {
        std::unordered_map<Symbol, Eigen::VectorXd> total_mktcap;  // yuan
    };

    explicit IndustryStyleCalculator(MktCapData mktcap = {});

    std::string group_name() const override { return "industry_style"; }

    FeatureSet compute(
        const std::vector<BarSeries>& series,
        const std::unordered_map<Symbol, Instrument>& instruments) const override;

    // --- Individual factor helpers (static for unit-testing) ---------------

    // Industry relative strength: stock return minus industry median return.
    // |stock_ret|: return for a single stock (scalar).
    // |industry_returns|: returns for all stocks in the same industry.
    // Returns: stock_ret - median(industry_returns).
    static double industry_relative_strength(
        double stock_ret,
        const Eigen::VectorXd& industry_returns);

    // Compute equal-weighted industry return over a window.
    // |member_returns|: matrix where each column is a member's return series.
    // Returns: (T,) vector of industry returns.
    static Eigen::VectorXd industry_momentum(
        const Eigen::MatrixXd& member_returns, int window);

    // Market-cap quantile assignment (quintile by default).
    // |log_mktcaps|: log(market_cap) for N stocks at a single date.
    // |num_groups|: number of quantile groups (default 5).
    // Returns: (N,) vector of group labels in [0, num_groups-1].
    static Eigen::VectorXd mktcap_quantile(
        const Eigen::VectorXd& log_mktcaps, int num_groups = 5);

    // Median of non-NaN values
    static double nan_median(const Eigen::VectorXd& v);

private:
    MktCapData mktcap_;

    // Group stocks by SWIndustry, returning symbol lists per industry.
    static std::unordered_map<SWIndustry, std::vector<int>>
    group_by_industry(
        const std::vector<Symbol>& symbols,
        const std::unordered_map<Symbol, Instrument>& instruments);

    // Extract daily return series from bars
    static Eigen::VectorXd extract_daily_returns(const BarSeries& bs);

    // Compute cumulative return over window from daily returns
    static Eigen::VectorXd cumulative_return(
        const Eigen::VectorXd& daily_returns, int window);
};

} // namespace trade
