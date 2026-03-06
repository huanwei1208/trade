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
// InteractionCalculator  (Priority P7 -- Cross / Interaction Features)
// ============================================================================
//
// Manually constructed interaction features that encode economic meaning.
// These are multiplicative interactions (product of two ranked features)
// plus a few ratio/conditional constructions.  All inputs are assumed to
// be pre-computed feature columns from other calculators (or can be
// computed from raw BarSeries as needed).
//
// ----  Reversal x Liquidity (7 features)  ----
//   1.  reversal_x_turnover_surge    rank(-ret_5d) * rank(delta_turnover_5d)
//       Short-term reversal is stronger when accompanied by unusual volume.
//
//   2.  reversal_x_amihud            rank(-ret_5d) * rank(amihud_20d)
//       Reversal in illiquid names tends to be more persistent.
//
//   3.  reversal_x_volume_ratio      rank(-ret_5d) * rank(volume_ratio_20d)
//       Volume spike amplifies mean-reversion signal.
//
//   4.  momentum_x_turnover          rank(ret_60d) * rank(turnover_rate_20d)
//       High-turnover momentum is more likely informed.
//
//   5.  momentum_x_low_vol           rank(ret_60d) * rank(-realized_vol_20d)
//       Low-vol momentum is a quality momentum signal.
//
//   6.  momentum_x_northbound        rank(ret_60d) * rank(north_chg_rate_5d)
//       Northbound capital validates momentum direction.
//
//   7.  reversal_x_vwap_dev          rank(-ret_5d) * rank(-vwap_dev)
//       Reversal when close is below VWAP (selling exhaustion).
//
// ----  Limit x Volatility (5 features)  ----
//   8.  limit_dist_x_vol             rank(dist_to_limit_up) * rank(realized_vol_20d)
//       Stocks near limit with high vol may break through.
//
//   9.  limit_dist_x_turnover        rank(dist_to_limit_up) * rank(turnover_rate_5d)
//       Near-limit with heavy trading signals strong demand.
//
//   10. limit_count_x_reversal       rank(limit_up_count_20d) * rank(-ret_5d)
//       Stocks that recently hit limits and pull back may bounce.
//
//   11. limit_dist_x_north           rank(dist_to_limit_up) * rank(north_chg_rate_5d)
//       Northbound buying near-limit stocks confirms conviction.
//
//   12. gap_x_vol                    rank(abs(open_gap)) * rank(realized_vol_20d)
//       Large gap with high vol indicates regime shift.
//
// ----  Auction x Gap (3 features)  ----
//   13. auction_x_gap                rank(auction_imbalance) * rank(open_gap)
//       Auction direction confirms the gap direction.
//
//   14. auction_x_reversal           rank(auction_imbalance) * rank(-ret_5d)
//       Auction buy imbalance on a beaten-down stock signals recovery.
//
//   15. auction_x_limit_dist         rank(auction_imbalance) * rank(dist_to_limit_up)
//       Strong auction near limit increases breakout probability.
//
// ----  Sentiment x Margin (4 features)  ----
//   16. margin_x_momentum            rank(margin_chg_5d) * rank(ret_60d)
//       Leveraged capital chasing momentum.
//
//   17. margin_x_reversal            rank(margin_chg_5d) * rank(-ret_5d)
//       Margin increase on dips may signal contrarian conviction.
//
//   18. margin_x_vol                 rank(margin_to_float) * rank(realized_vol_20d)
//       Highly leveraged + volatile = forced liquidation risk.
//
//   19. short_x_reversal             rank(short_sell_ratio) * rank(-ret_5d)
//       Heavy short selling on dips = potential short squeeze.
//
// ----  Industry x Macro (5 features)  ----
//   20. ind_strength_x_macro_bull    rank(ind_rel_strength_20d) * I(regime=bull)
//       Industry outperformance amplified in bull regimes.
//
//   21. ind_strength_x_macro_bear    rank(ind_rel_strength_20d) * I(regime=bear)
//       Industry outperformance dampened in bear regimes.
//
//   22. ind_mom_x_mktcap             rank(ind_mom_20d) * rank(log_mktcap)
//       Large-cap industry momentum (sector rotation by institutions).
//
//   23. ind_strength_x_north         rank(ind_rel_strength_20d) * rank(north_chg_rate_5d)
//       Northbound capital flows confirm industry rotation.
//
//   24. ind_strength_x_margin        rank(ind_rel_strength_20d) * rank(margin_chg_5d)
//       Leveraged money confirms industry trend.
//
// ----  Amihud x Volatility (3 features)  ----
//   25. amihud_x_vol                 rank(amihud_20d) * rank(realized_vol_20d)
//       Illiquid + volatile = tail risk premium.
//
//   26. amihud_x_reversal            rank(amihud_20d) * rank(-ret_5d)
//       Reversal in illiquid names (wider spread, larger mean-reversion).
//
//   27. amihud_x_mktcap              rank(amihud_20d) * rank(-log_mktcap)
//       Small + illiquid = higher liquidity premium.
//
// ----  Calendar interactions (3 features)  ----
//   28. spring_x_reversal            I(spring_festival_window) * rank(-ret_5d)
//       Pre-holiday reversal effect.
//
//   29. month_end_x_momentum         I(month_end) * rank(ret_20d)
//       Month-end window dressing / rebalancing flow.
//
//   30. vol_regime_x_reversal        rank(vol_of_vol_20d) * rank(-ret_5d)
//       Reversal is stronger when vol-of-vol is high (uncertainty).
//
class InteractionCalculator : public FeatureCalculator {
public:
    std::string group_name() const override { return "interaction"; }

    // Requires a pre-computed FeatureSet from the base calculators.
    // If |base_features| is provided, interaction features are derived
    // from its columns.  Otherwise, they are computed from raw BarSeries.
    FeatureSet compute(
        const std::vector<BarSeries>& series,
        const std::unordered_map<Symbol, Instrument>& instruments) const override;

    // Overload that accepts pre-computed base features for efficiency.
    FeatureSet compute_from_base(
        const FeatureSet& base_features,
        const std::vector<Date>& dates) const;

    // Set the current market regime (used for regime-conditional features).
    void set_regime(Regime regime) { current_regime_ = regime; }

    // --- Static helpers ---------------------------------------------------

    // Multiplicative interaction of two ranked vectors.
    // Both inputs should be rank-transformed [0,1].
    // Output: element-wise product, NaN if either input is NaN.
    static Eigen::VectorXd rank_interaction(
        const Eigen::VectorXd& rank_a,
        const Eigen::VectorXd& rank_b);

    // Conditional interaction: value * indicator.
    // |indicator|: binary vector (0 or 1).
    // Output: value * indicator, 0 where indicator is 0.
    static Eigen::VectorXd conditional_interaction(
        const Eigen::VectorXd& value,
        const Eigen::VectorXd& indicator);

    // Cross-sectional rank within a date slice (wrapper around cs_rank).
    static Eigen::VectorXd rank_column(
        const Eigen::VectorXd& col,
        const std::unordered_map<Date, std::vector<int>>& date_indices);

    // Feature names for all 30 interaction features
    static std::vector<std::string> feature_names();

private:
    Regime current_regime_ = Regime::kShock;

    // Lookup a column from base features, return empty if not found
    static Eigen::VectorXd safe_col(
        const FeatureSet& fs, const std::string& name);
};

} // namespace trade
