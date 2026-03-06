#include "trade/features/volatility.h"
#include <cmath>

namespace trade {

Eigen::VectorXd VolatilityCalculator::extract_daily_returns(const BarSeries& bs) {
    if (bs.size() < 2) return {};
    int n = static_cast<int>(bs.size());
    Eigen::VectorXd ret(n);
    ret(0) = 0.0;
    for (int i = 1; i < n; ++i) {
        double prev = bs[i - 1].close;
        ret(i) = (prev > 0) ? (bs[i].close / prev - 1.0) : 0.0;
    }
    return ret;
}

void VolatilityCalculator::extract_hlc(const BarSeries& bs,
                                        Eigen::VectorXd& highs,
                                        Eigen::VectorXd& lows,
                                        Eigen::VectorXd& closes) {
    int n = static_cast<int>(bs.size());
    highs.resize(n);
    lows.resize(n);
    closes.resize(n);
    for (int i = 0; i < n; ++i) {
        highs(i) = bs[i].high;
        lows(i) = bs[i].low;
        closes(i) = bs[i].close;
    }
}

Eigen::VectorXd VolatilityCalculator::compute_market_return(
    const std::vector<BarSeries>& series, int max_len) {
    Eigen::VectorXd mkt = Eigen::VectorXd::Zero(max_len);
    Eigen::VectorXd count = Eigen::VectorXd::Zero(max_len);

    for (const auto& bs : series) {
        auto ret = extract_daily_returns(bs);
        int n = static_cast<int>(ret.size());
        int offset = max_len - n;
        for (int i = 0; i < n; ++i) {
            if (!std::isnan(ret(i)) && (offset + i) >= 0) {
                mkt(offset + i) += ret(i);
                count(offset + i) += 1.0;
            }
        }
    }

    for (int i = 0; i < max_len; ++i) {
        mkt(i) = (count(i) > 0) ? mkt(i) / count(i) : 0.0;
    }
    return mkt;
}

Eigen::VectorXd VolatilityCalculator::realized_volatility(
    const Eigen::VectorXd& daily_returns, int window) {
    return rolling_std(daily_returns, window);
}

Eigen::VectorXd VolatilityCalculator::high_low_amplitude(
    const Eigen::VectorXd& highs,
    const Eigen::VectorXd& lows,
    const Eigen::VectorXd& closes,
    int window) {
    int n = static_cast<int>(highs.size());
    Eigen::VectorXd amp(n);
    for (int i = 0; i < n; ++i) {
        amp(i) = (closes(i) > 0) ? (highs(i) - lows(i)) / closes(i) : 0.0;
    }
    return rolling_mean(amp, window);
}

Eigen::VectorXd VolatilityCalculator::vol_of_vol(
    const Eigen::VectorXd& vol_series, int window) {
    return rolling_std(vol_series, window);
}

Eigen::VectorXd VolatilityCalculator::idiosyncratic_volatility(
    const Eigen::VectorXd& stock_returns,
    const Eigen::VectorXd& market_returns,
    int window) {
    int n = static_cast<int>(stock_returns.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    for (int i = window - 1; i < n; ++i) {
        double sum_x = 0, sum_y = 0, sum_xx = 0, sum_xy = 0;
        int count = 0;
        for (int j = i - window + 1; j <= i; ++j) {
            if (!std::isnan(stock_returns(j)) && !std::isnan(market_returns(j))) {
                double x = market_returns(j);
                double y = stock_returns(j);
                sum_x += x; sum_y += y;
                sum_xx += x * x; sum_xy += x * y;
                ++count;
            }
        }
        if (count < 5) continue;

        double mean_x = sum_x / count;
        double mean_y = sum_y / count;
        double var_x = sum_xx / count - mean_x * mean_x;
        double beta = (var_x > 1e-15) ? (sum_xy / count - mean_x * mean_y) / var_x : 0.0;
        double alpha = mean_y - beta * mean_x;

        double sum_eps2 = 0;
        for (int j = i - window + 1; j <= i; ++j) {
            if (!std::isnan(stock_returns(j)) && !std::isnan(market_returns(j))) {
                double eps = stock_returns(j) - alpha - beta * market_returns(j);
                sum_eps2 += eps * eps;
            }
        }
        result(i) = std::sqrt(sum_eps2 / (count - 2));
    }
    return result;
}

FeatureSet VolatilityCalculator::compute(
    const std::vector<BarSeries>& series,
    const std::unordered_map<Symbol, Instrument>& /*instruments*/) const {
    if (series.empty()) return {};

    int max_len = 0;
    for (const auto& bs : series) {
        max_len = std::max(max_len, static_cast<int>(bs.size()));
    }
    if (max_len < 20) return {};

    auto market_ret = compute_market_return(series, max_len);
    int n_stocks = static_cast<int>(series.size());

    constexpr int n_features = 16;
    std::vector<std::string> feat_names = {
        "realized_vol_20d", "realized_vol_60d",
        "realized_vol_20d_cs_rank", "realized_vol_60d_cs_rank",
        "hilo_amp_20d", "hilo_amp_60d", "hilo_amp_20d_cs_rank",
        "vol_of_vol_20d", "vol_of_vol_20d_cs_rank",
        "idio_vol_20d", "idio_vol_60d", "idio_vol_20d_cs_rank",
        "realized_vol_20d_ts_z", "realized_vol_60d_ts_z",
        "hilo_amp_20d_ts_z", "vol_of_vol_20d_ts_z"
    };

    Eigen::MatrixXd mat(n_stocks, n_features);
    mat.setConstant(std::numeric_limits<double>::quiet_NaN());

    std::vector<Symbol> symbols;
    std::vector<Date> dates;

    for (int s = 0; s < n_stocks; ++s) {
        symbols.push_back(series[s].symbol);
        dates.push_back(series[s].empty() ? Date{} : series[s].bars.back().date);

        auto daily_ret = extract_daily_returns(series[s]);
        int n = static_cast<int>(daily_ret.size());
        if (n < 20) continue;

        auto rv20 = realized_volatility(daily_ret, 20);
        auto rv60 = realized_volatility(daily_ret, 60);

        Eigen::VectorXd highs, lows, closes;
        extract_hlc(series[s], highs, lows, closes);
        auto ha20 = high_low_amplitude(highs, lows, closes, 20);
        auto ha60 = high_low_amplitude(highs, lows, closes, 60);

        auto vov20 = vol_of_vol(rv20, 20);

        int offset = max_len - n;
        Eigen::VectorXd mkt_slice = market_ret.segment(std::max(0, offset), n);
        auto iv20 = idiosyncratic_volatility(daily_ret, mkt_slice, 20);
        auto iv60 = idiosyncratic_volatility(daily_ret, mkt_slice, 60);

        auto last = [](const Eigen::VectorXd& v) -> double {
            return v.size() > 0 ? v(v.size() - 1) : std::numeric_limits<double>::quiet_NaN();
        };

        mat(s, 0) = last(rv20);
        mat(s, 1) = last(rv60);
        mat(s, 4) = last(ha20);
        mat(s, 5) = last(ha60);
        mat(s, 7) = last(vov20);
        mat(s, 9) = last(iv20);
        mat(s, 10) = last(iv60);

        // ts_z scores
        mat(s, 12) = last(ts_zscore(rv20, 120));
        mat(s, 13) = last(ts_zscore(rv60, 240));
        mat(s, 14) = last(ts_zscore(ha20, 120));
        mat(s, 15) = last(ts_zscore(vov20, 120));
    }

    // Cross-sectional ranks
    mat.col(2) = cs_rank(mat.col(0));   // realized_vol_20d_cs_rank
    mat.col(3) = cs_rank(mat.col(1));   // realized_vol_60d_cs_rank
    mat.col(6) = cs_rank(mat.col(4));   // hilo_amp_20d_cs_rank
    mat.col(8) = cs_rank(mat.col(7));   // vol_of_vol_20d_cs_rank
    mat.col(11) = cs_rank(mat.col(9));  // idio_vol_20d_cs_rank

    FeatureSet fs;
    fs.names = std::move(feat_names);
    fs.symbols = std::move(symbols);
    fs.dates = std::move(dates);
    fs.matrix = std::move(mat);
    return fs;
}

} // namespace trade
