#include "trade/features/momentum.h"
#include <cmath>
#include <numeric>

namespace trade {

Eigen::VectorXd MomentumCalculator::extract_daily_returns(const BarSeries& bs) {
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

Eigen::VectorXd MomentumCalculator::compute_market_return(
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

Eigen::VectorXd MomentumCalculator::cumulative_return(
    const Eigen::VectorXd& daily_returns, int window) {
    int n = static_cast<int>(daily_returns.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    for (int i = window - 1; i < n; ++i) {
        double cum = 1.0;
        for (int j = i - window + 1; j <= i; ++j) {
            if (!std::isnan(daily_returns(j))) {
                cum *= (1.0 + daily_returns(j));
            }
        }
        result(i) = cum - 1.0;
    }
    return result;
}

Eigen::VectorXd MomentumCalculator::idiosyncratic_volatility(
    const Eigen::VectorXd& stock_returns,
    const Eigen::VectorXd& market_returns,
    int window) {
    int n = static_cast<int>(stock_returns.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    for (int i = window - 1; i < n; ++i) {
        // Collect valid pairs in the window
        double sum_x = 0, sum_y = 0, sum_xx = 0, sum_xy = 0;
        int count = 0;
        for (int j = i - window + 1; j <= i; ++j) {
            if (!std::isnan(stock_returns(j)) && !std::isnan(market_returns(j))) {
                double x = market_returns(j);
                double y = stock_returns(j);
                sum_x += x;
                sum_y += y;
                sum_xx += x * x;
                sum_xy += x * y;
                ++count;
            }
        }
        if (count < 5) continue;

        // OLS: y = alpha + beta * x + eps
        double mean_x = sum_x / count;
        double mean_y = sum_y / count;
        double var_x = sum_xx / count - mean_x * mean_x;
        double beta = (var_x > 1e-15) ? (sum_xy / count - mean_x * mean_y) / var_x : 0.0;
        double alpha = mean_y - beta * mean_x;

        // Compute std of residuals
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

Eigen::VectorXd MomentumCalculator::reversal_rank(const Eigen::VectorXd& returns) {
    Eigen::VectorXd neg_ret = -returns;
    return cs_rank(neg_ret);
}

Eigen::VectorXd MomentumCalculator::momentum_rank(const Eigen::VectorXd& returns) {
    return cs_rank(returns);
}

FeatureSet MomentumCalculator::compute(
    const std::vector<BarSeries>& series,
    const std::unordered_map<Symbol, Instrument>& /*instruments*/) const {
    if (series.empty()) return {};

    // Find max length across all series
    int max_len = 0;
    for (const auto& bs : series) {
        max_len = std::max(max_len, static_cast<int>(bs.size()));
    }
    if (max_len < 5) return {};

    // Compute market returns for idiosyncratic vol
    auto market_ret = compute_market_return(series, max_len);

    // For panel data: each (symbol, date) is a row
    // We compute per-stock time series first, then assemble
    int n_stocks = static_cast<int>(series.size());

    // Per-stock features as time series
    struct StockFeatures {
        Eigen::VectorXd ret_5d, ret_20d, ret_60d, ret_120d;
        Eigen::VectorXd idio_vol_20d, idio_vol_60d;
        Eigen::VectorXd ret_5d_ts_z, ret_20d_ts_z, ret_60d_ts_z, ret_120d_ts_z;
    };

    std::vector<StockFeatures> stock_feats(n_stocks);

    for (int s = 0; s < n_stocks; ++s) {
        auto daily_ret = extract_daily_returns(series[s]);
        int n = static_cast<int>(daily_ret.size());
        if (n < 5) continue;

        // Cumulative returns at various windows
        stock_feats[s].ret_5d = cumulative_return(daily_ret, 5);
        stock_feats[s].ret_20d = cumulative_return(daily_ret, 20);
        stock_feats[s].ret_60d = cumulative_return(daily_ret, 60);
        stock_feats[s].ret_120d = cumulative_return(daily_ret, 120);

        // Idiosyncratic volatility
        int offset = max_len - n;
        Eigen::VectorXd mkt_slice = market_ret.segment(std::max(0, offset), n);
        stock_feats[s].idio_vol_20d = idiosyncratic_volatility(daily_ret, mkt_slice, 20);
        stock_feats[s].idio_vol_60d = idiosyncratic_volatility(daily_ret, mkt_slice, 60);

        // Time-series z-scores
        stock_feats[s].ret_5d_ts_z = ts_zscore(stock_feats[s].ret_5d, 60);
        stock_feats[s].ret_20d_ts_z = ts_zscore(stock_feats[s].ret_20d, 120);
        stock_feats[s].ret_60d_ts_z = ts_zscore(stock_feats[s].ret_60d, 240);
        stock_feats[s].ret_120d_ts_z = ts_zscore(stock_feats[s].ret_120d, 240);
    }

    // Assemble panel: use the last date as the observation point
    // For simplicity, use the last bar date from each stock
    // In production, you'd align dates properly
    constexpr int n_features = 14;
    std::vector<std::string> feat_names = {
        "ret_5d", "ret_20d", "ret_60d", "ret_120d",
        "ret_5d_cs_rank", "ret_20d_cs_rank", "ret_60d_cs_rank", "ret_120d_cs_rank",
        "idio_vol_20d", "idio_vol_60d",
        "ret_5d_ts_z", "ret_20d_ts_z", "ret_60d_ts_z", "ret_120d_ts_z"
    };

    Eigen::MatrixXd mat(n_stocks, n_features);
    mat.setConstant(std::numeric_limits<double>::quiet_NaN());

    std::vector<Symbol> symbols;
    std::vector<Date> dates;

    for (int s = 0; s < n_stocks; ++s) {
        symbols.push_back(series[s].symbol);
        dates.push_back(series[s].empty() ? Date{} : series[s].bars.back().date);

        auto last_or_nan = [](const Eigen::VectorXd& v) -> double {
            if (v.size() == 0) return std::numeric_limits<double>::quiet_NaN();
            return v(v.size() - 1);
        };

        mat(s, 0) = last_or_nan(stock_feats[s].ret_5d);
        mat(s, 1) = last_or_nan(stock_feats[s].ret_20d);
        mat(s, 2) = last_or_nan(stock_feats[s].ret_60d);
        mat(s, 3) = last_or_nan(stock_feats[s].ret_120d);
        // cs_rank columns filled below
        mat(s, 8) = last_or_nan(stock_feats[s].idio_vol_20d);
        mat(s, 9) = last_or_nan(stock_feats[s].idio_vol_60d);
        mat(s, 10) = last_or_nan(stock_feats[s].ret_5d_ts_z);
        mat(s, 11) = last_or_nan(stock_feats[s].ret_20d_ts_z);
        mat(s, 12) = last_or_nan(stock_feats[s].ret_60d_ts_z);
        mat(s, 13) = last_or_nan(stock_feats[s].ret_120d_ts_z);
    }

    // Cross-sectional ranks (reversal for 5d/20d, momentum for 60d/120d)
    mat.col(4) = reversal_rank(mat.col(0));   // rank(-ret_5d)
    mat.col(5) = reversal_rank(mat.col(1));   // rank(-ret_20d)
    mat.col(6) = momentum_rank(mat.col(2));   // rank(ret_60d)
    mat.col(7) = momentum_rank(mat.col(3));   // rank(ret_120d)

    FeatureSet fs;
    fs.names = std::move(feat_names);
    fs.symbols = std::move(symbols);
    fs.dates = std::move(dates);
    fs.matrix = std::move(mat);
    return fs;
}

} // namespace trade
