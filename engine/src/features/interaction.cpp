#include "trade/features/interaction.h"
#include <cmath>

namespace trade {

// ============================================================================
// Static helpers
// ============================================================================

Eigen::VectorXd InteractionCalculator::rank_interaction(
    const Eigen::VectorXd& rank_a,
    const Eigen::VectorXd& rank_b) {
    int n = static_cast<int>(rank_a.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    for (int i = 0; i < n; ++i) {
        if (!std::isnan(rank_a(i)) && !std::isnan(rank_b(i))) {
            result(i) = rank_a(i) * rank_b(i);
        }
    }
    return result;
}

Eigen::VectorXd InteractionCalculator::conditional_interaction(
    const Eigen::VectorXd& value,
    const Eigen::VectorXd& indicator) {
    int n = static_cast<int>(value.size());
    Eigen::VectorXd result(n);
    result.setConstant(0.0);

    for (int i = 0; i < n; ++i) {
        if (!std::isnan(value(i)) && !std::isnan(indicator(i))) {
            result(i) = value(i) * indicator(i);
        } else if (std::isnan(value(i))) {
            result(i) = std::numeric_limits<double>::quiet_NaN();
        }
    }
    return result;
}

Eigen::VectorXd InteractionCalculator::rank_column(
    const Eigen::VectorXd& col,
    const std::unordered_map<Date, std::vector<int>>& date_indices) {
    // If date_indices is empty, rank the whole column at once
    if (date_indices.empty()) {
        return cs_rank(col);
    }

    int n = static_cast<int>(col.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    for (const auto& [date, indices] : date_indices) {
        if (indices.empty()) continue;

        // Extract slice for this date
        Eigen::VectorXd slice(static_cast<int>(indices.size()));
        for (int i = 0; i < static_cast<int>(indices.size()); ++i) {
            slice(i) = col(indices[i]);
        }

        // Rank within date
        auto ranked = cs_rank(slice);
        for (int i = 0; i < static_cast<int>(indices.size()); ++i) {
            result(indices[i]) = ranked(i);
        }
    }
    return result;
}

std::vector<std::string> InteractionCalculator::feature_names() {
    return {
        // Reversal x Liquidity (7)
        "reversal_x_turnover_surge",       // 0
        "reversal_x_amihud",               // 1
        "reversal_x_volume_ratio",         // 2
        "momentum_x_turnover",             // 3
        "momentum_x_low_vol",              // 4
        "momentum_x_northbound",           // 5
        "reversal_x_vwap_dev",             // 6
        // Limit x Volatility (5)
        "limit_dist_x_vol",                // 7
        "limit_dist_x_turnover",           // 8
        "limit_count_x_reversal",          // 9
        "limit_dist_x_north",             // 10
        "gap_x_vol",                       // 11
        // Auction x Gap (3)
        "auction_x_gap",                   // 12
        "auction_x_reversal",              // 13
        "auction_x_limit_dist",            // 14
        // Sentiment x Margin (4)
        "margin_x_momentum",              // 15
        "margin_x_reversal",              // 16
        "margin_x_vol",                    // 17
        "short_x_reversal",               // 18
        // Industry x Macro (5)
        "ind_strength_x_macro_bull",       // 19
        "ind_strength_x_macro_bear",       // 20
        "ind_mom_x_mktcap",               // 21
        "ind_strength_x_north",           // 22
        "ind_strength_x_margin",          // 23
        // Amihud x Volatility (3)
        "amihud_x_vol",                    // 24
        "amihud_x_reversal",              // 25
        "amihud_x_mktcap",                // 26
        // Calendar interactions (3)
        "spring_x_reversal",               // 27
        "month_end_x_momentum",            // 28
        "vol_regime_x_reversal",           // 29
    };
}

Eigen::VectorXd InteractionCalculator::safe_col(
    const FeatureSet& fs, const std::string& name) {
    return fs.column(name);
}

// ============================================================================
// compute_from_base: the main interaction logic using pre-computed features
// ============================================================================

FeatureSet InteractionCalculator::compute_from_base(
    const FeatureSet& base_features,
    const std::vector<Date>& /*dates*/) const {

    int n = base_features.num_observations();
    if (n == 0) return {};

    auto names = feature_names();
    constexpr int n_features = 30;
    Eigen::MatrixXd mat(n, n_features);
    mat.setConstant(std::numeric_limits<double>::quiet_NaN());

    // Helper: get ranked column from base features, rank if not already ranked
    auto get_rank = [&](const std::string& name) -> Eigen::VectorXd {
        auto col = safe_col(base_features, name);
        if (col.size() == 0) {
            return Eigen::VectorXd::Constant(n, std::numeric_limits<double>::quiet_NaN());
        }
        return cs_rank(col);
    };

    auto get_neg_rank = [&](const std::string& name) -> Eigen::VectorXd {
        auto col = safe_col(base_features, name);
        if (col.size() == 0) {
            return Eigen::VectorXd::Constant(n, std::numeric_limits<double>::quiet_NaN());
        }
        return cs_rank(-col);
    };

    auto get_col = [&](const std::string& name) -> Eigen::VectorXd {
        auto col = safe_col(base_features, name);
        if (col.size() == 0) {
            return Eigen::VectorXd::Constant(n, std::numeric_limits<double>::quiet_NaN());
        }
        return col;
    };

    // Pre-compute commonly used ranked features
    auto rank_neg_ret_5d    = get_neg_rank("ret_5d");             // reversal
    auto rank_ret_60d       = get_rank("ret_60d");                // momentum
    auto rank_ret_20d       = get_rank("ret_20d");
    auto rank_delta_to      = get_rank("delta_turnover_5d");      // turnover surge
    auto rank_amihud        = get_rank("amihud_20d");
    auto rank_vol_ratio     = get_rank("volume_ratio_20d");
    auto rank_turnover_20d  = get_rank("turnover_rate_20d");
    auto rank_turnover_5d   = get_rank("turnover_rate_5d");
    auto rank_neg_rv20      = get_neg_rank("realized_vol_20d");   // low vol
    auto rank_rv20          = get_rank("realized_vol_20d");
    auto rank_north         = get_rank("north_chg_rate_5d");
    auto rank_neg_vwap      = get_neg_rank("vwap_dev");
    auto rank_dist_up       = get_rank("dist_to_limit_up");
    auto rank_lim_up_cnt    = get_rank("limit_up_count_20d");
    auto rank_auction       = get_rank("auction_imbalance");
    auto rank_gap           = get_rank("open_gap");
    auto rank_margin_chg_5d = get_rank("margin_chg_5d");
    auto rank_margin_float  = get_rank("margin_to_float");
    auto rank_short_sell    = get_rank("short_sell_ratio");
    auto rank_ind_str_20d   = get_rank("ind_rel_strength_20d");
    auto rank_ind_mom_20d   = get_rank("ind_mom_20d");
    auto rank_log_mktcap    = get_rank("log_mktcap");
    auto rank_neg_mktcap    = get_neg_rank("log_mktcap");
    auto rank_vov20         = get_rank("vol_of_vol_20d");
    auto is_spring          = get_col("is_spring_festival");
    auto is_month_end       = get_col("is_month_end");

    // Compute abs(open_gap) ranked
    auto gap_col = get_col("open_gap");
    Eigen::VectorXd abs_gap(n);
    for (int i = 0; i < n; ++i) {
        abs_gap(i) = std::isnan(gap_col(i)) ? std::numeric_limits<double>::quiet_NaN()
                                             : std::abs(gap_col(i));
    }
    auto rank_abs_gap = cs_rank(abs_gap);

    // ---- Reversal x Liquidity (7) ----
    mat.col(0) = rank_interaction(rank_neg_ret_5d, rank_delta_to);
    mat.col(1) = rank_interaction(rank_neg_ret_5d, rank_amihud);
    mat.col(2) = rank_interaction(rank_neg_ret_5d, rank_vol_ratio);
    mat.col(3) = rank_interaction(rank_ret_60d, rank_turnover_20d);
    mat.col(4) = rank_interaction(rank_ret_60d, rank_neg_rv20);
    mat.col(5) = rank_interaction(rank_ret_60d, rank_north);
    mat.col(6) = rank_interaction(rank_neg_ret_5d, rank_neg_vwap);

    // ---- Limit x Volatility (5) ----
    mat.col(7) = rank_interaction(rank_dist_up, rank_rv20);
    mat.col(8) = rank_interaction(rank_dist_up, rank_turnover_5d);
    mat.col(9) = rank_interaction(rank_lim_up_cnt, rank_neg_ret_5d);
    mat.col(10) = rank_interaction(rank_dist_up, rank_north);
    mat.col(11) = rank_interaction(rank_abs_gap, rank_rv20);

    // ---- Auction x Gap (3) ----
    mat.col(12) = rank_interaction(rank_auction, rank_gap);
    mat.col(13) = rank_interaction(rank_auction, rank_neg_ret_5d);
    mat.col(14) = rank_interaction(rank_auction, rank_dist_up);

    // ---- Sentiment x Margin (4) ----
    mat.col(15) = rank_interaction(rank_margin_chg_5d, rank_ret_60d);
    mat.col(16) = rank_interaction(rank_margin_chg_5d, rank_neg_ret_5d);
    mat.col(17) = rank_interaction(rank_margin_float, rank_rv20);
    mat.col(18) = rank_interaction(rank_short_sell, rank_neg_ret_5d);

    // ---- Industry x Macro (5) ----
    // Regime-conditional: create binary indicator vectors
    Eigen::VectorXd bull_indicator = Eigen::VectorXd::Constant(n,
        (current_regime_ == Regime::kBull) ? 1.0 : 0.0);
    Eigen::VectorXd bear_indicator = Eigen::VectorXd::Constant(n,
        (current_regime_ == Regime::kBear) ? 1.0 : 0.0);

    mat.col(19) = conditional_interaction(rank_ind_str_20d, bull_indicator);
    mat.col(20) = conditional_interaction(rank_ind_str_20d, bear_indicator);
    mat.col(21) = rank_interaction(rank_ind_mom_20d, rank_log_mktcap);
    mat.col(22) = rank_interaction(rank_ind_str_20d, rank_north);
    mat.col(23) = rank_interaction(rank_ind_str_20d, rank_margin_chg_5d);

    // ---- Amihud x Volatility (3) ----
    mat.col(24) = rank_interaction(rank_amihud, rank_rv20);
    mat.col(25) = rank_interaction(rank_amihud, rank_neg_ret_5d);
    mat.col(26) = rank_interaction(rank_amihud, rank_neg_mktcap);

    // ---- Calendar interactions (3) ----
    mat.col(27) = conditional_interaction(rank_neg_ret_5d, is_spring);
    mat.col(28) = conditional_interaction(rank_ret_20d, is_month_end);
    mat.col(29) = rank_interaction(rank_vov20, rank_neg_ret_5d);

    FeatureSet fs;
    fs.names = names;
    fs.symbols = base_features.symbols;
    fs.dates = base_features.dates;
    fs.matrix = std::move(mat);
    return fs;
}

// ============================================================================
// compute: compute from raw BarSeries (builds base features internally)
// ============================================================================

FeatureSet InteractionCalculator::compute(
    const std::vector<BarSeries>& series,
    const std::unordered_map<Symbol, Instrument>& /*instruments*/) const {
    if (series.empty()) return {};

    int n_stocks = static_cast<int>(series.size());

    // Build minimal base features from raw bars for interaction computation
    // Extract the key raw features needed for interactions
    auto names = feature_names();
    constexpr int n_features = 30;

    Eigen::MatrixXd mat(n_stocks, n_features);
    mat.setConstant(std::numeric_limits<double>::quiet_NaN());

    std::vector<Symbol> symbols;
    std::vector<Date> dates;

    // Extract per-stock values needed for interactions
    Eigen::VectorXd ret_5d_col(n_stocks), ret_20d_col(n_stocks), ret_60d_col(n_stocks);
    Eigen::VectorXd turnover_5d_col(n_stocks), turnover_20d_col(n_stocks);
    Eigen::VectorXd delta_to_col(n_stocks), vol_col(n_stocks);
    ret_5d_col.setConstant(std::numeric_limits<double>::quiet_NaN());
    ret_20d_col.setConstant(std::numeric_limits<double>::quiet_NaN());
    ret_60d_col.setConstant(std::numeric_limits<double>::quiet_NaN());
    turnover_5d_col.setConstant(std::numeric_limits<double>::quiet_NaN());
    turnover_20d_col.setConstant(std::numeric_limits<double>::quiet_NaN());
    delta_to_col.setConstant(std::numeric_limits<double>::quiet_NaN());
    vol_col.setConstant(std::numeric_limits<double>::quiet_NaN());

    for (int s = 0; s < n_stocks; ++s) {
        const auto& bs = series[s];
        symbols.push_back(bs.symbol);
        dates.push_back(bs.empty() ? Date{} : bs.bars.back().date);

        int n = static_cast<int>(bs.size());
        if (n < 5) continue;

        // Daily returns
        Eigen::VectorXd daily_ret(n);
        daily_ret(0) = 0.0;
        for (int i = 1; i < n; ++i) {
            double prev = bs[i - 1].close;
            daily_ret(i) = (prev > 0) ? (bs[i].close / prev - 1.0) : 0.0;
        }

        // Cumulative returns
        auto cum_ret = [&](int w) -> double {
            if (n < w) return std::numeric_limits<double>::quiet_NaN();
            double cum = 1.0;
            for (int i = n - w; i < n; ++i) {
                cum *= (1.0 + daily_ret(i));
            }
            return cum - 1.0;
        };

        ret_5d_col(s) = cum_ret(5);
        ret_20d_col(s) = cum_ret(20);
        ret_60d_col(s) = (n >= 60) ? cum_ret(60) : std::numeric_limits<double>::quiet_NaN();

        // Turnover rates
        Eigen::VectorXd to_rates(n);
        for (int i = 0; i < n; ++i) to_rates(i) = bs[i].turnover_rate;
        auto to_5d = rolling_mean(to_rates, 5);
        auto to_20d = rolling_mean(to_rates, 20);
        turnover_5d_col(s) = (to_5d.size() > 0) ? to_5d(to_5d.size() - 1) : std::numeric_limits<double>::quiet_NaN();
        turnover_20d_col(s) = (to_20d.size() > 0) ? to_20d(to_20d.size() - 1) : std::numeric_limits<double>::quiet_NaN();

        if (n >= 20 && !std::isnan(turnover_5d_col(s)) && !std::isnan(turnover_20d_col(s)) &&
            turnover_20d_col(s) > 1e-12) {
            delta_to_col(s) = turnover_5d_col(s) / turnover_20d_col(s) - 1.0;
        }

        // Realized vol 20d
        if (n >= 20) {
            auto rv = rolling_std(daily_ret, 20);
            vol_col(s) = rv(rv.size() - 1);
        }
    }

    // Build rank vectors
    auto rank_neg_ret_5d = cs_rank(-ret_5d_col);
    auto rank_ret_60d = cs_rank(ret_60d_col);
    auto rank_ret_20d = cs_rank(ret_20d_col);
    auto rank_delta_to = cs_rank(delta_to_col);
    auto rank_turnover_5d = cs_rank(turnover_5d_col);
    auto rank_turnover_20d = cs_rank(turnover_20d_col);
    auto rank_vol = cs_rank(vol_col);
    auto rank_neg_vol = cs_rank(-vol_col);

    // Reversal x Liquidity (simplified from raw bars)
    mat.col(0) = rank_interaction(rank_neg_ret_5d, rank_delta_to);
    // amihud and volume_ratio require more computation; use turnover as proxy
    mat.col(1) = rank_interaction(rank_neg_ret_5d, rank_neg_vol);     // proxy for illiquidity
    mat.col(2) = rank_interaction(rank_neg_ret_5d, rank_turnover_5d); // proxy for vol ratio
    mat.col(3) = rank_interaction(rank_ret_60d, rank_turnover_20d);
    mat.col(4) = rank_interaction(rank_ret_60d, rank_neg_vol);
    // northbound, vwap_dev require optional Bar fields
    mat.col(6) = rank_interaction(rank_neg_ret_5d, rank_neg_vol);

    // Limit x Volatility (limited from raw bars)
    mat.col(7) = rank_interaction(rank_vol, rank_turnover_5d);
    mat.col(8) = rank_interaction(rank_turnover_5d, rank_vol);
    mat.col(9) = rank_interaction(rank_neg_ret_5d, rank_vol);
    mat.col(11) = rank_interaction(rank_vol, rank_vol);

    // Margin / Industry features are NaN without base features
    // Calendar interactions
    mat.col(29) = rank_interaction(rank_vol, rank_neg_ret_5d);

    FeatureSet fs;
    fs.names = names;
    fs.symbols = std::move(symbols);
    fs.dates = std::move(dates);
    fs.matrix = std::move(mat);
    return fs;
}

} // namespace trade
