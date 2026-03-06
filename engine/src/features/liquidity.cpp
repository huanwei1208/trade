#include "trade/features/liquidity.h"
#include <cmath>

namespace trade {

// ============================================================================
// Extract helpers
// ============================================================================

Eigen::VectorXd LiquidityCalculator::extract_turnover_rates(const BarSeries& bs) {
    int n = static_cast<int>(bs.size());
    if (n == 0) return {};
    Eigen::VectorXd v(n);
    for (int i = 0; i < n; ++i) {
        v(i) = bs[i].turnover_rate;
    }
    return v;
}

Eigen::VectorXd LiquidityCalculator::extract_daily_returns(const BarSeries& bs) {
    int n = static_cast<int>(bs.size());
    if (n < 2) return {};
    Eigen::VectorXd ret(n);
    ret(0) = 0.0;
    for (int i = 1; i < n; ++i) {
        double prev = bs[i - 1].close;
        ret(i) = (prev > 0) ? (bs[i].close / prev - 1.0) : 0.0;
    }
    return ret;
}

Eigen::VectorXd LiquidityCalculator::extract_amounts(const BarSeries& bs) {
    int n = static_cast<int>(bs.size());
    if (n == 0) return {};
    Eigen::VectorXd v(n);
    for (int i = 0; i < n; ++i) {
        v(i) = bs[i].amount;
    }
    return v;
}

Eigen::VectorXd LiquidityCalculator::extract_volumes(const BarSeries& bs) {
    int n = static_cast<int>(bs.size());
    if (n == 0) return {};
    Eigen::VectorXd v(n);
    for (int i = 0; i < n; ++i) {
        v(i) = static_cast<double>(bs[i].volume);
    }
    return v;
}

Eigen::VectorXd LiquidityCalculator::extract_closes(const BarSeries& bs) {
    int n = static_cast<int>(bs.size());
    if (n == 0) return {};
    Eigen::VectorXd v(n);
    for (int i = 0; i < n; ++i) {
        v(i) = bs[i].close;
    }
    return v;
}

Eigen::VectorXd LiquidityCalculator::extract_vwaps(const BarSeries& bs) {
    int n = static_cast<int>(bs.size());
    if (n == 0) return {};
    Eigen::VectorXd v(n);
    for (int i = 0; i < n; ++i) {
        v(i) = bs[i].vwap;
    }
    return v;
}

// ============================================================================
// Static factor helpers
// ============================================================================

Eigen::VectorXd LiquidityCalculator::rolling_turnover(
    const Eigen::VectorXd& turnover_rates, int window) {
    return rolling_mean(turnover_rates, window);
}

Eigen::VectorXd LiquidityCalculator::delta_turnover(
    const Eigen::VectorXd& turnover_rates,
    int short_window, int long_window) {
    int n = static_cast<int>(turnover_rates.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    auto short_ma = rolling_mean(turnover_rates, short_window);
    auto long_ma = rolling_mean(turnover_rates, long_window);

    for (int i = 0; i < n; ++i) {
        if (!std::isnan(short_ma(i)) && !std::isnan(long_ma(i)) && long_ma(i) > 1e-12) {
            result(i) = short_ma(i) / long_ma(i) - 1.0;
        }
    }
    return result;
}

Eigen::VectorXd LiquidityCalculator::amihud_illiquidity(
    const Eigen::VectorXd& daily_returns,
    const Eigen::VectorXd& volumes_yuan,
    int window,
    double scale) {
    int n = static_cast<int>(daily_returns.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    // Compute per-day |return| / volume_yuan
    Eigen::VectorXd ratio(n);
    ratio.setConstant(std::numeric_limits<double>::quiet_NaN());
    for (int i = 0; i < n; ++i) {
        if (!std::isnan(daily_returns(i)) && !std::isnan(volumes_yuan(i)) &&
            volumes_yuan(i) > 1e-8) {
            ratio(i) = std::abs(daily_returns(i)) / volumes_yuan(i) * scale;
        }
    }

    // Rolling mean of the ratio
    for (int i = window - 1; i < n; ++i) {
        double sum = 0;
        int count = 0;
        for (int j = i - window + 1; j <= i; ++j) {
            if (!std::isnan(ratio(j))) {
                sum += ratio(j);
                ++count;
            }
        }
        if (count > 0) {
            result(i) = sum / count;
        }
    }
    return result;
}

Eigen::VectorXd LiquidityCalculator::volume_ratio(
    const Eigen::VectorXd& volumes, int window) {
    int n = static_cast<int>(volumes.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    auto ma = rolling_mean(volumes, window);
    for (int i = 0; i < n; ++i) {
        if (!std::isnan(volumes(i)) && !std::isnan(ma(i)) && ma(i) > 1e-8) {
            result(i) = volumes(i) / ma(i);
        }
    }
    return result;
}

Eigen::VectorXd LiquidityCalculator::vwap_deviation(
    const Eigen::VectorXd& closes,
    const Eigen::VectorXd& vwaps) {
    int n = static_cast<int>(closes.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    for (int i = 0; i < n; ++i) {
        if (!std::isnan(closes(i)) && !std::isnan(vwaps(i)) && vwaps(i) > 1e-8) {
            result(i) = closes(i) / vwaps(i) - 1.0;
        }
    }
    return result;
}

// ============================================================================
// Main compute
// ============================================================================

FeatureSet LiquidityCalculator::compute(
    const std::vector<BarSeries>& series,
    const std::unordered_map<Symbol, Instrument>& /*instruments*/) const {
    if (series.empty()) return {};

    int n_stocks = static_cast<int>(series.size());

    // 17 features total
    constexpr int n_features = 17;
    std::vector<std::string> feat_names = {
        "turnover_rate_5d",             // 0
        "turnover_rate_20d",            // 1
        "delta_turnover_5d",            // 2
        "turnover_rate_5d_cs_rank",     // 3
        "delta_turnover_5d_cs_rank",    // 4
        "amihud_20d",                   // 5
        "amihud_60d",                   // 6
        "amihud_20d_cs_rank",           // 7
        "volume_ratio_20d",             // 8
        "volume_ratio_20d_cs_rank",     // 9
        "vwap_dev",                     // 10
        "vwap_dev_cs_rank",             // 11
        "turnover_rate_5d_ts_z",        // 12
        "delta_turnover_5d_ts_z",       // 13
        "amihud_20d_ts_z",              // 14
        "volume_ratio_20d_ts_z",        // 15
        "vwap_dev_ts_z",                // 16
    };

    Eigen::MatrixXd mat(n_stocks, n_features);
    mat.setConstant(std::numeric_limits<double>::quiet_NaN());

    std::vector<Symbol> symbols;
    std::vector<Date> dates;

    for (int s = 0; s < n_stocks; ++s) {
        symbols.push_back(series[s].symbol);
        dates.push_back(series[s].empty() ? Date{} : series[s].bars.back().date);

        int n = static_cast<int>(series[s].size());
        if (n < 5) continue;

        auto turnover_rates = extract_turnover_rates(series[s]);
        auto daily_ret = extract_daily_returns(series[s]);
        auto amounts = extract_amounts(series[s]);
        auto volumes = extract_volumes(series[s]);
        auto closes = extract_closes(series[s]);
        auto vwaps = extract_vwaps(series[s]);

        // Turnover features
        auto to_5d = rolling_turnover(turnover_rates, 5);
        auto to_20d = rolling_turnover(turnover_rates, 20);
        auto delta_to = delta_turnover(turnover_rates, 5, 20);

        // Amihud illiquidity: use amount (volume in yuan)
        auto amihud_20 = amihud_illiquidity(daily_ret, amounts, 20);
        auto amihud_60 = amihud_illiquidity(daily_ret, amounts, 60);

        // Volume ratio
        auto vol_ratio = volume_ratio(volumes, 20);

        // VWAP deviation
        auto vwap_dev = vwap_deviation(closes, vwaps);

        auto last = [](const Eigen::VectorXd& v) -> double {
            return v.size() > 0 ? v(v.size() - 1) : std::numeric_limits<double>::quiet_NaN();
        };

        mat(s, 0) = last(to_5d);
        mat(s, 1) = last(to_20d);
        mat(s, 2) = last(delta_to);
        // cs_rank cols 3, 4 filled below
        mat(s, 5) = last(amihud_20);
        mat(s, 6) = last(amihud_60);
        // cs_rank col 7 filled below
        mat(s, 8) = last(vol_ratio);
        // cs_rank col 9 filled below
        mat(s, 10) = last(vwap_dev);
        // cs_rank col 11 filled below

        // Time-series z-scores
        mat(s, 12) = last(ts_zscore(to_5d, 60));
        mat(s, 13) = last(ts_zscore(delta_to, 60));
        mat(s, 14) = last(ts_zscore(amihud_20, 120));
        mat(s, 15) = last(ts_zscore(vol_ratio, 60));
        mat(s, 16) = last(ts_zscore(vwap_dev, 60));
    }

    // Cross-sectional ranks
    mat.col(3) = cs_rank(mat.col(0));    // turnover_rate_5d_cs_rank
    mat.col(4) = cs_rank(mat.col(2));    // delta_turnover_5d_cs_rank
    mat.col(7) = cs_rank(mat.col(5));    // amihud_20d_cs_rank
    mat.col(9) = cs_rank(mat.col(8));    // volume_ratio_20d_cs_rank
    mat.col(11) = cs_rank(mat.col(10));  // vwap_dev_cs_rank

    FeatureSet fs;
    fs.names = std::move(feat_names);
    fs.symbols = std::move(symbols);
    fs.dates = std::move(dates);
    fs.matrix = std::move(mat);
    return fs;
}

} // namespace trade
