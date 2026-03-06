#include "trade/features/price_limit.h"
#include <cmath>

namespace trade {

// ============================================================================
// Constructor
// ============================================================================

PriceLimitCalculator::PriceLimitCalculator(AuctionMap auction)
    : auction_(std::move(auction)) {}

// ============================================================================
// Extract helpers
// ============================================================================

void PriceLimitCalculator::extract_limit_fields(
    const BarSeries& bs,
    const Instrument& inst,
    Eigen::VectorXd& closes,
    Eigen::VectorXd& limit_ups,
    Eigen::VectorXd& limit_downs,
    Eigen::VectorXd& hit_up_flags,
    Eigen::VectorXd& hit_down_flags) {

    int n = static_cast<int>(bs.size());
    closes.resize(n);
    limit_ups.resize(n);
    limit_downs.resize(n);
    hit_up_flags.resize(n);
    hit_down_flags.resize(n);

    double pct = price_limit_pct(inst.board);

    for (int i = 0; i < n; ++i) {
        closes(i) = bs[i].close;

        // Use limit prices from Bar if available
        if (bs[i].limit_up > 0) {
            limit_ups(i) = bs[i].limit_up;
            limit_downs(i) = bs[i].limit_down;
            hit_up_flags(i) = bs[i].hit_limit_up ? 1.0 : 0.0;
            hit_down_flags(i) = bs[i].hit_limit_down ? 1.0 : 0.0;
        } else {
            // Compute from prev_close and board
            double prev = bs[i].prev_close;
            if (prev > 0) {
                double lu = prev * (1.0 + pct);
                double ld = prev * (1.0 - pct);
                // Round to tick (0.01 yuan)
                limit_ups(i) = static_cast<int>(lu * 100 + 0.5) / 100.0;
                limit_downs(i) = static_cast<int>(ld * 100 + 0.5) / 100.0;
                hit_up_flags(i) = (bs[i].close >= limit_ups(i) - 0.005) ? 1.0 : 0.0;
                hit_down_flags(i) = (bs[i].close <= limit_downs(i) + 0.005) ? 1.0 : 0.0;
            } else {
                limit_ups(i) = std::numeric_limits<double>::quiet_NaN();
                limit_downs(i) = std::numeric_limits<double>::quiet_NaN();
                hit_up_flags(i) = 0.0;
                hit_down_flags(i) = 0.0;
            }
        }
    }
}

Eigen::VectorXd PriceLimitCalculator::extract_opens(const BarSeries& bs) {
    int n = static_cast<int>(bs.size());
    if (n == 0) return {};
    Eigen::VectorXd v(n);
    for (int i = 0; i < n; ++i) {
        v(i) = bs[i].open;
    }
    return v;
}

Eigen::VectorXd PriceLimitCalculator::extract_prev_closes(const BarSeries& bs) {
    int n = static_cast<int>(bs.size());
    if (n == 0) return {};
    Eigen::VectorXd v(n);
    for (int i = 0; i < n; ++i) {
        v(i) = bs[i].prev_close;
    }
    return v;
}

// ============================================================================
// Static factor helpers
// ============================================================================

Eigen::VectorXd PriceLimitCalculator::distance_to_limit_up(
    const Eigen::VectorXd& closes,
    const Eigen::VectorXd& limit_ups) {
    int n = static_cast<int>(closes.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    for (int i = 0; i < n; ++i) {
        if (!std::isnan(closes(i)) && !std::isnan(limit_ups(i)) && closes(i) > 1e-8) {
            result(i) = (limit_ups(i) - closes(i)) / closes(i);
        }
    }
    return result;
}

Eigen::VectorXd PriceLimitCalculator::distance_to_limit_down(
    const Eigen::VectorXd& closes,
    const Eigen::VectorXd& limit_downs) {
    int n = static_cast<int>(closes.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    for (int i = 0; i < n; ++i) {
        if (!std::isnan(closes(i)) && !std::isnan(limit_downs(i)) && closes(i) > 1e-8) {
            result(i) = (closes(i) - limit_downs(i)) / closes(i);
        }
    }
    return result;
}

Eigen::VectorXd PriceLimitCalculator::limit_hit_count(
    const Eigen::VectorXd& hit_flags, int window) {
    return rolling_sum(hit_flags, window);
}

Eigen::VectorXd PriceLimitCalculator::open_gap(
    const Eigen::VectorXd& opens,
    const Eigen::VectorXd& prev_closes) {
    int n = static_cast<int>(opens.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    for (int i = 0; i < n; ++i) {
        if (!std::isnan(opens(i)) && !std::isnan(prev_closes(i)) &&
            prev_closes(i) > 1e-8) {
            result(i) = opens(i) / prev_closes(i) - 1.0;
        }
    }
    return result;
}

Eigen::VectorXd PriceLimitCalculator::auction_imbalance(
    const Eigen::VectorXd& buy_volumes,
    const Eigen::VectorXd& sell_volumes) {
    int n = static_cast<int>(buy_volumes.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    for (int i = 0; i < n; ++i) {
        if (!std::isnan(buy_volumes(i)) && !std::isnan(sell_volumes(i))) {
            double total = buy_volumes(i) + sell_volumes(i);
            if (total > 1e-8) {
                result(i) = (buy_volumes(i) - sell_volumes(i)) / total;
            }
        }
    }
    return result;
}

// ============================================================================
// Main compute
// ============================================================================

FeatureSet PriceLimitCalculator::compute(
    const std::vector<BarSeries>& series,
    const std::unordered_map<Symbol, Instrument>& instruments) const {
    if (series.empty()) return {};

    int n_stocks = static_cast<int>(series.size());

    // 14 features total
    constexpr int n_features = 14;
    std::vector<std::string> feat_names = {
        "dist_to_limit_up",             // 0
        "dist_to_limit_down",           // 1
        "dist_to_limit_up_cs_rank",     // 2
        "dist_to_limit_down_cs_rank",   // 3
        "limit_up_count_20d",           // 4
        "limit_down_count_20d",         // 5
        "limit_up_count_20d_cs_rank",   // 6
        "limit_down_count_20d_cs_rank", // 7
        "open_gap",                     // 8
        "open_gap_cs_rank",             // 9
        "open_gap_ts_z",                // 10
        "auction_imbalance",            // 11
        "auction_imbalance_cs_rank",    // 12
        "auction_imbalance_ts_z",       // 13
    };

    Eigen::MatrixXd mat(n_stocks, n_features);
    mat.setConstant(std::numeric_limits<double>::quiet_NaN());

    std::vector<Symbol> symbols;
    std::vector<Date> dates;

    for (int s = 0; s < n_stocks; ++s) {
        const auto& bs = series[s];
        symbols.push_back(bs.symbol);
        dates.push_back(bs.empty() ? Date{} : bs.bars.back().date);

        int n = static_cast<int>(bs.size());
        if (n < 1) continue;

        // Look up instrument for this stock
        Instrument inst;
        auto it = instruments.find(bs.symbol);
        if (it != instruments.end()) {
            inst = it->second;
        }

        // Extract limit fields
        Eigen::VectorXd closes, limit_ups, limit_downs, hit_up, hit_down;
        extract_limit_fields(bs, inst, closes, limit_ups, limit_downs, hit_up, hit_down);

        auto dist_up = distance_to_limit_up(closes, limit_ups);
        auto dist_down = distance_to_limit_down(closes, limit_downs);

        auto lu_count = limit_hit_count(hit_up, 20);
        auto ld_count = limit_hit_count(hit_down, 20);

        auto opens = extract_opens(bs);
        auto prev_cls = extract_prev_closes(bs);
        auto gap = open_gap(opens, prev_cls);

        auto last = [](const Eigen::VectorXd& v) -> double {
            return v.size() > 0 ? v(v.size() - 1) : std::numeric_limits<double>::quiet_NaN();
        };

        mat(s, 0) = last(dist_up);
        mat(s, 1) = last(dist_down);
        // cs_rank cols 2, 3 filled below
        mat(s, 4) = last(lu_count);
        mat(s, 5) = last(ld_count);
        // cs_rank cols 6, 7 filled below
        mat(s, 8) = last(gap);
        // cs_rank col 9 filled below
        mat(s, 10) = last(ts_zscore(gap, 60));

        // Auction imbalance (from external data if available)
        auto auction_it = auction_.find(bs.symbol);
        if (auction_it != auction_.end()) {
            const auto& ad = auction_it->second;
            auto aimb = auction_imbalance(ad.buy_volume, ad.sell_volume);
            mat(s, 11) = last(aimb);
            mat(s, 13) = last(ts_zscore(aimb, 60));
        }
    }

    // Cross-sectional ranks
    mat.col(2) = cs_rank(mat.col(0));    // dist_to_limit_up_cs_rank
    mat.col(3) = cs_rank(mat.col(1));    // dist_to_limit_down_cs_rank
    mat.col(6) = cs_rank(mat.col(4));    // limit_up_count_20d_cs_rank
    mat.col(7) = cs_rank(mat.col(5));    // limit_down_count_20d_cs_rank
    mat.col(9) = cs_rank(mat.col(8));    // open_gap_cs_rank
    mat.col(12) = cs_rank(mat.col(11));  // auction_imbalance_cs_rank

    FeatureSet fs;
    fs.names = std::move(feat_names);
    fs.symbols = std::move(symbols);
    fs.dates = std::move(dates);
    fs.matrix = std::move(mat);
    return fs;
}

} // namespace trade
