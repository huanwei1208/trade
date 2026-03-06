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
// PriceLimitCalculator  (Priority P4 -- Trading State / Price-limit Factors)
// ============================================================================
//
// A-share specific factors related to the daily price-limit mechanism,
// opening auction behaviour, and recent limit-hit history.  These factors
// are critical for alpha capture in limit-hit regimes and IPO-day trading.
//
// Features computed:
//
// --- Distance to limit ---
//   dist_to_limit_up       (limit_up  - close) / close
//   dist_to_limit_down     (close - limit_down) / close
//   dist_to_limit_up_cs_rank   cross-sectional rank
//   dist_to_limit_down_cs_rank cross-sectional rank
//
// --- Limit-hit count ---
//   limit_up_count_20d     number of days stock hit upper limit in last 20d
//   limit_down_count_20d   number of days stock hit lower limit in last 20d
//   limit_up_count_20d_cs_rank   cross-sectional rank
//   limit_down_count_20d_cs_rank cross-sectional rank
//
// --- Open gap ---
//   open_gap               (open / prev_close - 1)
//   open_gap_cs_rank       cross-sectional rank
//   open_gap_ts_z          ts_zscore(open_gap, 60)
//
// --- Auction imbalance ---
//   auction_imbalance      (buy_volume - sell_volume) /
//                          (buy_volume + sell_volume)
//   auction_imbalance_cs_rank  cross-sectional rank
//   auction_imbalance_ts_z     ts_zscore(auction_imbalance, 60)
//
// NOTE: limit_up / limit_down are computed from prev_close and Board.
//       auction_imbalance requires external call auction data; when
//       unavailable, the feature is set to NaN.
//
class PriceLimitCalculator : public FeatureCalculator {
public:
    // External auction data: per-stock series of (buy_volume, sell_volume)
    // from the opening call auction.
    struct AuctionData {
        Eigen::VectorXd buy_volume;
        Eigen::VectorXd sell_volume;
    };

    using AuctionMap = std::unordered_map<Symbol, AuctionData>;

    explicit PriceLimitCalculator(AuctionMap auction = {});

    std::string group_name() const override { return "price_limit"; }

    FeatureSet compute(
        const std::vector<BarSeries>& series,
        const std::unordered_map<Symbol, Instrument>& instruments) const override;

    // --- Individual factor helpers (static for unit-testing) ---------------

    // Distance to price limit:
    //   up:   (limit_up  - close) / close   (always >= 0 for normal stocks)
    //   down: (close - limit_down) / close   (always >= 0 for normal stocks)
    static Eigen::VectorXd distance_to_limit_up(
        const Eigen::VectorXd& closes,
        const Eigen::VectorXd& limit_ups);

    static Eigen::VectorXd distance_to_limit_down(
        const Eigen::VectorXd& closes,
        const Eigen::VectorXd& limit_downs);

    // Count of limit-hit days in a rolling window.
    // |hit_flags| is a binary vector (1 = hit, 0 = not hit).
    static Eigen::VectorXd limit_hit_count(
        const Eigen::VectorXd& hit_flags, int window);

    // Open gap: open / prev_close - 1
    static Eigen::VectorXd open_gap(
        const Eigen::VectorXd& opens,
        const Eigen::VectorXd& prev_closes);

    // Auction imbalance: (buy - sell) / (buy + sell)
    // Returns NaN where buy + sell == 0.
    static Eigen::VectorXd auction_imbalance(
        const Eigen::VectorXd& buy_volumes,
        const Eigen::VectorXd& sell_volumes);

private:
    AuctionMap auction_;

    // Extract limit-related fields from BarSeries.
    // If limit prices are zero, they are recomputed from prev_close + board.
    static void extract_limit_fields(
        const BarSeries& bs,
        const Instrument& inst,
        Eigen::VectorXd& closes,
        Eigen::VectorXd& limit_ups,
        Eigen::VectorXd& limit_downs,
        Eigen::VectorXd& hit_up_flags,
        Eigen::VectorXd& hit_down_flags);

    static Eigen::VectorXd extract_opens(const BarSeries& bs);
    static Eigen::VectorXd extract_prev_closes(const BarSeries& bs);
};

} // namespace trade
