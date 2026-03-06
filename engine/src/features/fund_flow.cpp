#include "trade/features/fund_flow.h"
#include <cmath>

namespace trade {

// ============================================================================
// Constructor
// ============================================================================

FundFlowCalculator::FundFlowCalculator(FloatMktCap float_mktcap)
    : float_mktcap_(std::move(float_mktcap)) {}

// ============================================================================
// Extract helpers -- extract optional Bar fields, NaN where unavailable
// ============================================================================

Eigen::VectorXd FundFlowCalculator::extract_north_net_buy(const BarSeries& bs) {
    int n = static_cast<int>(bs.size());
    if (n == 0) return {};
    Eigen::VectorXd v(n);
    v.setConstant(std::numeric_limits<double>::quiet_NaN());
    for (int i = 0; i < n; ++i) {
        if (bs[i].north_net_buy.has_value()) {
            v(i) = bs[i].north_net_buy.value();
        }
    }
    return v;
}

Eigen::VectorXd FundFlowCalculator::extract_margin_balance(const BarSeries& bs) {
    int n = static_cast<int>(bs.size());
    if (n == 0) return {};
    Eigen::VectorXd v(n);
    v.setConstant(std::numeric_limits<double>::quiet_NaN());
    for (int i = 0; i < n; ++i) {
        if (bs[i].margin_balance.has_value()) {
            v(i) = bs[i].margin_balance.value();
        }
    }
    return v;
}

Eigen::VectorXd FundFlowCalculator::extract_short_sell_volume(const BarSeries& bs) {
    int n = static_cast<int>(bs.size());
    if (n == 0) return {};
    Eigen::VectorXd v(n);
    v.setConstant(std::numeric_limits<double>::quiet_NaN());
    for (int i = 0; i < n; ++i) {
        if (bs[i].short_sell_volume.has_value()) {
            v(i) = bs[i].short_sell_volume.value();
        }
    }
    return v;
}

Eigen::VectorXd FundFlowCalculator::extract_total_volume(const BarSeries& bs) {
    int n = static_cast<int>(bs.size());
    if (n == 0) return {};
    Eigen::VectorXd v(n);
    for (int i = 0; i < n; ++i) {
        v(i) = static_cast<double>(bs[i].volume);
    }
    return v;
}

// ============================================================================
// Static factor helpers
// ============================================================================

Eigen::VectorXd FundFlowCalculator::north_net_buy_sum(
    const Eigen::VectorXd& daily_north, int window) {
    return rolling_sum(daily_north, window);
}

Eigen::VectorXd FundFlowCalculator::north_change_rate(
    const Eigen::VectorXd& daily_north,
    const Eigen::VectorXd& float_mktcap,
    int window) {
    int n = static_cast<int>(daily_north.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    auto north_sum = rolling_sum(daily_north, window);
    for (int i = 0; i < n; ++i) {
        if (!std::isnan(north_sum(i)) && i < static_cast<int>(float_mktcap.size()) &&
            !std::isnan(float_mktcap(i)) && float_mktcap(i) > 1e-8) {
            result(i) = north_sum(i) / float_mktcap(i);
        }
    }
    return result;
}

Eigen::VectorXd FundFlowCalculator::margin_to_float(
    const Eigen::VectorXd& margin_balance,
    const Eigen::VectorXd& float_mktcap) {
    int n = static_cast<int>(margin_balance.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    for (int i = 0; i < n; ++i) {
        if (!std::isnan(margin_balance(i)) && i < static_cast<int>(float_mktcap.size()) &&
            !std::isnan(float_mktcap(i)) && float_mktcap(i) > 1e-8) {
            result(i) = margin_balance(i) / float_mktcap(i);
        }
    }
    return result;
}

Eigen::VectorXd FundFlowCalculator::margin_change(
    const Eigen::VectorXd& margin_balance, int window) {
    int n = static_cast<int>(margin_balance.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    for (int i = window; i < n; ++i) {
        if (!std::isnan(margin_balance(i)) && !std::isnan(margin_balance(i - window)) &&
            std::abs(margin_balance(i - window)) > 1e-8) {
            result(i) = (margin_balance(i) - margin_balance(i - window)) /
                         margin_balance(i - window);
        }
    }
    return result;
}

Eigen::VectorXd FundFlowCalculator::short_sell_ratio(
    const Eigen::VectorXd& short_volume,
    const Eigen::VectorXd& total_volume) {
    int n = static_cast<int>(short_volume.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    for (int i = 0; i < n; ++i) {
        if (!std::isnan(short_volume(i)) && !std::isnan(total_volume(i)) &&
            total_volume(i) > 1e-8) {
            result(i) = short_volume(i) / total_volume(i);
        }
    }
    return result;
}

// ============================================================================
// Main compute
// ============================================================================

FeatureSet FundFlowCalculator::compute(
    const std::vector<BarSeries>& series,
    const std::unordered_map<Symbol, Instrument>& /*instruments*/) const {
    if (series.empty()) return {};

    int n_stocks = static_cast<int>(series.size());

    // 16 features total
    constexpr int n_features = 16;
    std::vector<std::string> feat_names = {
        "north_net_buy_5d",             // 0
        "north_net_buy_20d",            // 1
        "north_chg_rate_5d",            // 2
        "north_chg_rate_5d_cs_rank",    // 3
        "north_chg_rate_5d_ts_z",       // 4
        "margin_to_float",              // 5
        "margin_chg_5d",                // 6
        "margin_chg_20d",               // 7
        "margin_to_float_cs_rank",      // 8
        "margin_chg_5d_cs_rank",        // 9
        "margin_chg_20d_cs_rank",       // 10
        "margin_to_float_ts_z",         // 11
        "margin_chg_5d_ts_z",           // 12
        "short_sell_ratio",             // 13
        "short_sell_ratio_cs_rank",     // 14
        "short_sell_ratio_ts_z",        // 15
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
        if (n < 5) continue;

        auto north = extract_north_net_buy(bs);
        auto margin = extract_margin_balance(bs);
        auto short_vol = extract_short_sell_volume(bs);
        auto total_vol = extract_total_volume(bs);

        // Get float mktcap for this stock (if available)
        Eigen::VectorXd fmc;
        auto it = float_mktcap_.data.find(bs.symbol);
        if (it != float_mktcap_.data.end()) {
            fmc = it->second;
        }

        auto last = [](const Eigen::VectorXd& v) -> double {
            return v.size() > 0 ? v(v.size() - 1) : std::numeric_limits<double>::quiet_NaN();
        };

        // Northbound features
        auto north_5d = north_net_buy_sum(north, 5);
        auto north_20d = north_net_buy_sum(north, 20);
        mat(s, 0) = last(north_5d);
        mat(s, 1) = last(north_20d);

        if (fmc.size() > 0) {
            auto ncr_5d = north_change_rate(north, fmc, 5);
            mat(s, 2) = last(ncr_5d);
            mat(s, 4) = last(ts_zscore(ncr_5d, 60));
        }

        // Margin features
        if (fmc.size() > 0) {
            auto m2f = margin_to_float(margin, fmc);
            mat(s, 5) = last(m2f);
            mat(s, 11) = last(ts_zscore(m2f, 120));
        }

        auto mc_5d = margin_change(margin, 5);
        auto mc_20d = margin_change(margin, 20);
        mat(s, 6) = last(mc_5d);
        mat(s, 7) = last(mc_20d);
        mat(s, 12) = last(ts_zscore(mc_5d, 60));

        // Short sell features
        auto ssr = short_sell_ratio(short_vol, total_vol);
        mat(s, 13) = last(ssr);
        mat(s, 15) = last(ts_zscore(ssr, 60));
    }

    // Cross-sectional ranks
    mat.col(3)  = cs_rank(mat.col(2));   // north_chg_rate_5d_cs_rank
    mat.col(8)  = cs_rank(mat.col(5));   // margin_to_float_cs_rank
    mat.col(9)  = cs_rank(mat.col(6));   // margin_chg_5d_cs_rank
    mat.col(10) = cs_rank(mat.col(7));   // margin_chg_20d_cs_rank
    mat.col(14) = cs_rank(mat.col(13));  // short_sell_ratio_cs_rank

    FeatureSet fs;
    fs.names = std::move(feat_names);
    fs.symbols = std::move(symbols);
    fs.dates = std::move(dates);
    fs.matrix = std::move(mat);
    return fs;
}

} // namespace trade
