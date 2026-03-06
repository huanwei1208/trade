#include "trade/stats/descriptive.h"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <vector>

namespace trade {

// ===========================================================================
// Helpers (internal)
// ===========================================================================

namespace {

// Compute the daily return from a Bar (simple return = close/prev_close - 1)
inline double bar_return(const Bar& b) {
    return b.prev_close > 0.0 ? (b.close - b.prev_close) / b.prev_close : 0.0;
}

// Check if the bar hit the upper price limit (~10% for main board)
inline bool is_limit_up(const Bar& b) {
    if (b.prev_close <= 0.0) return false;
    double ret = (b.close - b.prev_close) / b.prev_close;
    return ret >= 0.095;  // approximate for main board; 9.5% threshold
}

// Check if the bar hit the lower price limit
inline bool is_limit_down(const Bar& b) {
    if (b.prev_close <= 0.0) return false;
    double ret = (b.close - b.prev_close) / b.prev_close;
    return ret <= -0.095;
}

// Check if a limit-up bar was "broken" (high hit limit but close didn't hold)
inline bool is_limit_up_broken(const Bar& b) {
    if (b.prev_close <= 0.0) return false;
    double limit_price = b.prev_close * 1.10;
    // high reached within 0.5% of limit-up but close failed to hold
    return (b.high >= limit_price * 0.995) && (b.close < limit_price * 0.995);
}

} // anonymous namespace

// ===========================================================================
// MarketOverview
// ===========================================================================

MarketOverview DescriptiveStats::market_overview(const MarketSnapshot& snapshot) {
    MarketOverview ov;
    ov.date = snapshot.date;
    ov.total_stocks = static_cast<int>(snapshot.bars.size());

    if (ov.total_stocks == 0) return ov;

    std::vector<double> returns;
    std::vector<double> turnover_rates;
    returns.reserve(ov.total_stocks);
    turnover_rates.reserve(ov.total_stocks);

    double sum_return = 0.0;
    double total_amount = 0.0;

    for (const auto& [sym, bar] : snapshot.bars) {
        double ret = bar_return(bar);
        returns.push_back(ret);
        sum_return += ret;
        total_amount += bar.amount;
        turnover_rates.push_back(bar.turnover_rate);

        if (ret > 1e-8) {
            ov.up_count++;
        } else if (ret < -1e-8) {
            ov.down_count++;
        } else {
            ov.flat_count++;
        }
    }

    ov.up_ratio = ov.total_stocks > 0
        ? static_cast<double>(ov.up_count) / static_cast<double>(ov.total_stocks)
        : 0.0;
    ov.total_amount = total_amount;
    ov.mean_return = sum_return / static_cast<double>(ov.total_stocks);

    // Median turnover rate
    std::sort(turnover_rates.begin(), turnover_rates.end());
    if (!turnover_rates.empty()) {
        size_t n = turnover_rates.size();
        ov.median_turnover = (n % 2 == 1)
            ? turnover_rates[n / 2]
            : 0.5 * (turnover_rates[n / 2 - 1] + turnover_rates[n / 2]);
    }

    return ov;
}

MarketOverview DescriptiveStats::market_overview(const std::vector<Bar>& bars, Date date) {
    MarketOverview ov;
    ov.date = date;
    ov.total_stocks = static_cast<int>(bars.size());

    if (ov.total_stocks == 0) return ov;

    std::vector<double> turnover_rates;
    turnover_rates.reserve(bars.size());
    double sum_return = 0.0;
    double total_amount = 0.0;

    for (const auto& bar : bars) {
        double ret = bar_return(bar);
        sum_return += ret;
        total_amount += bar.amount;
        turnover_rates.push_back(bar.turnover_rate);

        if (ret > 1e-8) {
            ov.up_count++;
        } else if (ret < -1e-8) {
            ov.down_count++;
        } else {
            ov.flat_count++;
        }
    }

    ov.up_ratio = static_cast<double>(ov.up_count) / static_cast<double>(ov.total_stocks);
    ov.total_amount = total_amount;
    ov.mean_return = sum_return / static_cast<double>(ov.total_stocks);

    std::sort(turnover_rates.begin(), turnover_rates.end());
    size_t n = turnover_rates.size();
    ov.median_turnover = (n % 2 == 1)
        ? turnover_rates[n / 2]
        : 0.5 * (turnover_rates[n / 2 - 1] + turnover_rates[n / 2]);

    return ov;
}

// ===========================================================================
// MoneyMakingEffect
// ===========================================================================

MoneyMakingEffect DescriptiveStats::money_making_effect(
    const MarketSnapshot& snapshot,
    const std::unordered_map<Symbol, double>& ma20_map) {

    MoneyMakingEffect mme;
    mme.date = snapshot.date;

    if (snapshot.bars.empty()) return mme;

    std::vector<double> returns;
    returns.reserve(snapshot.bars.size());

    int below_ma20_count = 0;
    int total_with_ma = 0;

    for (const auto& [sym, bar] : snapshot.bars) {
        double ret = bar_return(bar);
        returns.push_back(ret);

        // Limit-up / limit-down detection
        if (is_limit_up(bar)) {
            mme.limit_up_count++;
        }
        if (is_limit_down(bar)) {
            mme.limit_down_count++;
        }
        if (is_limit_up_broken(bar)) {
            mme.limit_up_broken_count++;
        }

        // Below 20-day MA check
        auto it = ma20_map.find(sym);
        if (it != ma20_map.end() && it->second > 0.0) {
            total_with_ma++;
            if (bar.close < it->second) {
                below_ma20_count++;
            }
        }
    }

    mme.below_20dma_ratio = total_with_ma > 0
        ? static_cast<double>(below_ma20_count) / static_cast<double>(total_with_ma)
        : 0.0;

    // Sort returns for percentile calculations
    std::sort(returns.begin(), returns.end());
    size_t n = returns.size();

    // Median return
    mme.median_return = (n % 2 == 1)
        ? returns[n / 2]
        : 0.5 * (returns[n / 2 - 1] + returns[n / 2]);

    // 25th and 75th percentile returns using linear interpolation
    {
        double idx25 = 0.25 * static_cast<double>(n - 1);
        size_t lo = static_cast<size_t>(std::floor(idx25));
        size_t hi = std::min(lo + 1, n - 1);
        double frac = idx25 - static_cast<double>(lo);
        mme.pct25_return = returns[lo] + frac * (returns[hi] - returns[lo]);
    }
    {
        double idx75 = 0.75 * static_cast<double>(n - 1);
        size_t lo = static_cast<size_t>(std::floor(idx75));
        size_t hi = std::min(lo + 1, n - 1);
        double frac = idx75 - static_cast<double>(lo);
        mme.pct75_return = returns[lo] + frac * (returns[hi] - returns[lo]);
    }

    return mme;
}

// ===========================================================================
// StyleExposure
// ===========================================================================

StyleExposure DescriptiveStats::style_exposure(
    const MarketSnapshot& snapshot,
    const std::unordered_map<Symbol, double>& market_caps,
    const std::unordered_map<Symbol, double>& growth_scores) {

    StyleExposure se;
    se.date = snapshot.date;

    if (snapshot.bars.empty()) return se;

    // --- Large/Small cap split ---
    // Collect (market_cap, return) pairs, then sort by cap descending.
    struct CapReturn {
        double cap;
        double ret;
    };
    std::vector<CapReturn> cap_returns;
    cap_returns.reserve(snapshot.bars.size());

    for (const auto& [sym, bar] : snapshot.bars) {
        auto it = market_caps.find(sym);
        if (it == market_caps.end()) continue;
        double ret = bar_return(bar);
        cap_returns.push_back({it->second, ret});
    }

    if (!cap_returns.empty()) {
        std::sort(cap_returns.begin(), cap_returns.end(),
                  [](const CapReturn& a, const CapReturn& b) {
                      return a.cap > b.cap;  // descending by cap
                  });

        size_t n = cap_returns.size();
        size_t decile = std::max<size_t>(1, n / 10);

        // Top decile (large cap) -- cap-weighted return
        double large_total_cap = 0.0;
        double large_weighted_ret = 0.0;
        for (size_t i = 0; i < decile; ++i) {
            large_total_cap += cap_returns[i].cap;
            large_weighted_ret += cap_returns[i].cap * cap_returns[i].ret;
        }
        se.large_cap_return = large_total_cap > 0.0
            ? large_weighted_ret / large_total_cap : 0.0;

        // Bottom decile (small cap) -- cap-weighted return
        double small_total_cap = 0.0;
        double small_weighted_ret = 0.0;
        for (size_t i = n - decile; i < n; ++i) {
            small_total_cap += cap_returns[i].cap;
            small_weighted_ret += cap_returns[i].cap * cap_returns[i].ret;
        }
        se.small_cap_return = small_total_cap > 0.0
            ? small_weighted_ret / small_total_cap : 0.0;

        se.large_small_spread = se.large_cap_return - se.small_cap_return;
    }

    // --- Growth/Value split ---
    // Sort by growth score descending; top half = growth, bottom half = value.
    struct ScoreReturn {
        double score;
        double ret;
    };
    std::vector<ScoreReturn> score_returns;
    score_returns.reserve(snapshot.bars.size());

    for (const auto& [sym, bar] : snapshot.bars) {
        auto it = growth_scores.find(sym);
        if (it == growth_scores.end()) continue;
        double ret = bar_return(bar);
        score_returns.push_back({it->second, ret});
    }

    if (!score_returns.empty()) {
        std::sort(score_returns.begin(), score_returns.end(),
                  [](const ScoreReturn& a, const ScoreReturn& b) {
                      return a.score > b.score;  // descending by growth score
                  });

        size_t n = score_returns.size();
        size_t half = n / 2;

        // Growth basket: top half, equal-weighted
        double growth_sum = 0.0;
        for (size_t i = 0; i < half; ++i) {
            growth_sum += score_returns[i].ret;
        }
        se.growth_return = half > 0 ? growth_sum / static_cast<double>(half) : 0.0;

        // Value basket: bottom half, equal-weighted
        double value_sum = 0.0;
        size_t value_count = n - half;
        for (size_t i = half; i < n; ++i) {
            value_sum += score_returns[i].ret;
        }
        se.value_return = value_count > 0 ? value_sum / static_cast<double>(value_count) : 0.0;

        se.growth_value_spread = se.growth_return - se.value_return;
    }

    return se;
}

// ===========================================================================
// StockDistributionStats
// ===========================================================================

StockDistributionStats DescriptiveStats::return_distribution(
    const Eigen::VectorXd& returns) {

    StockDistributionStats stats;
    int n = static_cast<int>(returns.size());
    stats.n = n;

    if (n == 0) return stats;

    stats.mean_return = returns.mean();
    stats.min_return = returns.minCoeff();
    stats.max_return = returns.maxCoeff();

    if (n >= 2) {
        double var = (returns.array() - stats.mean_return).square().sum()
                     / static_cast<double>(n - 1);
        stats.std_return = std::sqrt(var);
    }

    stats.skewness = DescriptiveStats::skewness(returns);
    stats.kurtosis = DescriptiveStats::kurtosis(returns);
    stats.pct5_return = DescriptiveStats::quantile(returns, 0.05);
    stats.pct95_return = DescriptiveStats::quantile(returns, 0.95);

    return stats;
}

// ===========================================================================
// Annualised Volatility
// ===========================================================================

double DescriptiveStats::annualised_volatility(
    const Eigen::VectorXd& returns,
    int trading_days_per_year) {

    int n = static_cast<int>(returns.size());
    if (n < 2) return 0.0;

    double mean = returns.mean();
    double var = (returns.array() - mean).square().sum() / static_cast<double>(n - 1);
    double daily_vol = std::sqrt(var);
    return daily_vol * std::sqrt(static_cast<double>(trading_days_per_year));
}

// ===========================================================================
// Correlation Matrix (Pearson)
// ===========================================================================

Eigen::MatrixXd DescriptiveStats::correlation_matrix(
    const Eigen::MatrixXd& return_matrix) {
    // return_matrix: N x T  (N symbols, T observations)
    int N = static_cast<int>(return_matrix.rows());
    int T = static_cast<int>(return_matrix.cols());

    if (N == 0 || T < 2) {
        return Eigen::MatrixXd::Identity(N, N);
    }

    // Center each row (subtract its mean)
    Eigen::MatrixXd centered = return_matrix;
    for (int i = 0; i < N; ++i) {
        double row_mean = centered.row(i).mean();
        centered.row(i).array() -= row_mean;
    }

    // Covariance = centered * centered^T / (T - 1)
    Eigen::MatrixXd cov = (centered * centered.transpose()) / static_cast<double>(T - 1);

    // Convert to correlation: corr_ij = cov_ij / sqrt(cov_ii * cov_jj)
    Eigen::VectorXd std_devs = cov.diagonal().array().sqrt();
    Eigen::MatrixXd corr(N, N);
    for (int i = 0; i < N; ++i) {
        for (int j = 0; j < N; ++j) {
            double denom = std_devs(i) * std_devs(j);
            corr(i, j) = denom > 1e-15 ? cov(i, j) / denom : (i == j ? 1.0 : 0.0);
        }
    }

    return corr;
}

// ===========================================================================
// Rank Correlation Matrix (Spearman)
// ===========================================================================

Eigen::MatrixXd DescriptiveStats::rank_correlation_matrix(
    const Eigen::MatrixXd& return_matrix) {
    // Convert each row to ranks, then compute Pearson on ranks.
    int N = static_cast<int>(return_matrix.rows());
    int T = static_cast<int>(return_matrix.cols());

    if (N == 0 || T < 2) {
        return Eigen::MatrixXd::Identity(N, N);
    }

    Eigen::MatrixXd ranked(N, T);
    for (int i = 0; i < N; ++i) {
        // Convert row i to a VectorXd, compute ranks, put back
        Eigen::VectorXd row = return_matrix.row(i).transpose();

        // Compute ranks with average tie-breaking
        std::vector<std::pair<double, int>> vals(T);
        for (int j = 0; j < T; ++j) {
            vals[j] = {row(j), j};
        }
        std::sort(vals.begin(), vals.end());

        Eigen::VectorXd ranks(T);
        int k = 0;
        while (k < T) {
            int start = k;
            while (k < T && vals[k].first == vals[start].first) {
                k++;
            }
            double avg_rank = 0.5 * (static_cast<double>(start) + static_cast<double>(k - 1));
            for (int m = start; m < k; ++m) {
                ranks(vals[m].second) = avg_rank;
            }
        }
        ranked.row(i) = ranks.transpose();
    }

    return correlation_matrix(ranked);
}

// ===========================================================================
// Quantile
// ===========================================================================

double DescriptiveStats::quantile(const Eigen::VectorXd& data, double q) {
    int n = static_cast<int>(data.size());
    if (n == 0) return 0.0;
    if (n == 1) return data(0);

    // Copy and sort
    std::vector<double> sorted(n);
    for (int i = 0; i < n; ++i) {
        sorted[i] = data(i);
    }
    std::sort(sorted.begin(), sorted.end());

    // Linear interpolation method
    double idx = q * static_cast<double>(n - 1);
    int lo = static_cast<int>(std::floor(idx));
    int hi = std::min(lo + 1, n - 1);
    double frac = idx - static_cast<double>(lo);
    return sorted[lo] + frac * (sorted[hi] - sorted[lo]);
}

// ===========================================================================
// Skewness
// ===========================================================================

double DescriptiveStats::skewness(const Eigen::VectorXd& data) {
    int n = static_cast<int>(data.size());
    if (n < 3) return 0.0;

    double mean = data.mean();
    Eigen::ArrayXd centered = data.array() - mean;

    double m2 = centered.square().sum() / static_cast<double>(n);
    double m3 = centered.cube().sum() / static_cast<double>(n);

    if (m2 < 1e-20) return 0.0;

    double sd = std::sqrt(m2);
    // Adjusted Fisher-Pearson skewness (sample correction)
    double g1 = m3 / (sd * sd * sd);
    // Apply bias correction: G1 = g1 * sqrt(n*(n-1)) / (n-2)
    double correction = std::sqrt(static_cast<double>(n) * static_cast<double>(n - 1))
                        / static_cast<double>(n - 2);
    return g1 * correction;
}

// ===========================================================================
// Excess Kurtosis
// ===========================================================================

double DescriptiveStats::kurtosis(const Eigen::VectorXd& data) {
    int n = static_cast<int>(data.size());
    if (n < 4) return 0.0;

    double mean = data.mean();
    Eigen::ArrayXd centered = data.array() - mean;

    double m2 = centered.square().sum() / static_cast<double>(n);
    double m4 = centered.pow(4).sum() / static_cast<double>(n);

    if (m2 < 1e-20) return 0.0;

    // Population kurtosis - 3 for excess
    double kurt_pop = m4 / (m2 * m2) - 3.0;

    // Bias-corrected sample excess kurtosis
    // G2 = ((n-1)/((n-2)*(n-3))) * ((n+1)*kurt_pop + 6)
    double nd = static_cast<double>(n);
    double excess = ((nd - 1.0) / ((nd - 2.0) * (nd - 3.0)))
                    * ((nd + 1.0) * kurt_pop + 6.0);
    return excess;
}

// ===========================================================================
// bars_to_returns
// ===========================================================================

Eigen::VectorXd DescriptiveStats::bars_to_returns(const std::vector<Bar>& bars) {
    if (bars.empty()) return Eigen::VectorXd();

    // First bar: use prev_close if available, otherwise skip it.
    // For each bar, compute simple return = (close - prev_close) / prev_close.
    std::vector<double> rets;
    rets.reserve(bars.size());

    for (const auto& bar : bars) {
        if (bar.prev_close > 0.0) {
            rets.push_back((bar.close - bar.prev_close) / bar.prev_close);
        }
    }

    Eigen::VectorXd result(static_cast<Eigen::Index>(rets.size()));
    for (size_t i = 0; i < rets.size(); ++i) {
        result(static_cast<Eigen::Index>(i)) = rets[i];
    }
    return result;
}

} // namespace trade
