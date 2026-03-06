#include "trade/stats/correlation.h"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <vector>

namespace trade {

// ===========================================================================
// ICDecayProfile member functions
// ===========================================================================

int ICDecayProfile::peak_horizon() const {
    if (results.empty()) return 0;

    int best_idx = 0;
    double best_abs_ic = 0.0;
    for (int i = 0; i < static_cast<int>(results.size()); ++i) {
        double abs_ic = std::abs(results[i].rank_ic);
        if (abs_ic > best_abs_ic) {
            best_abs_ic = abs_ic;
            best_idx = i;
        }
    }
    return results[best_idx].horizon;
}

int ICDecayProfile::half_life() const {
    if (results.empty()) return 0;

    // Find peak |rank_ic|
    double peak_abs_ic = 0.0;
    for (const auto& r : results) {
        double abs_ic = std::abs(r.rank_ic);
        if (abs_ic > peak_abs_ic) {
            peak_abs_ic = abs_ic;
        }
    }

    if (peak_abs_ic < 1e-15) return 0;

    double half_threshold = 0.5 * peak_abs_ic;

    // Find first horizon (after peak) where |IC| drops below half of peak
    bool past_peak = false;
    for (const auto& r : results) {
        double abs_ic = std::abs(r.rank_ic);
        if (std::abs(abs_ic - peak_abs_ic) < 1e-15) {
            past_peak = true;
            continue;
        }
        if (past_peak && abs_ic < half_threshold) {
            return r.horizon;
        }
    }

    // IC never decayed to half -- return last horizon
    return results.back().horizon;
}

// ===========================================================================
// Utility: to_ranks  -- fractional ranks in [0, 1] with average tie-breaking
// ===========================================================================

Eigen::VectorXd CorrelationAnalysis::to_ranks(const Eigen::VectorXd& values) {
    int n = static_cast<int>(values.size());
    if (n == 0) return Eigen::VectorXd();

    // Create index-value pairs and sort by value
    std::vector<std::pair<double, int>> indexed(n);
    for (int i = 0; i < n; ++i) {
        indexed[i] = {values(i), i};
    }
    std::sort(indexed.begin(), indexed.end());

    Eigen::VectorXd ranks(n);
    int k = 0;
    while (k < n) {
        int start = k;
        // Find all elements with the same value (ties)
        while (k < n && indexed[k].first == indexed[start].first) {
            ++k;
        }
        // Average rank for ties (0-based)
        double avg_rank = 0.5 * (static_cast<double>(start) + static_cast<double>(k - 1));
        for (int m = start; m < k; ++m) {
            ranks(indexed[m].second) = avg_rank;
        }
    }

    // Normalise to [0, 1]
    if (n > 1) {
        ranks.array() /= static_cast<double>(n - 1);
    } else {
        ranks(0) = 0.5;
    }

    return ranks;
}

// ===========================================================================
// Forward returns from a price vector
// ===========================================================================

Eigen::VectorXd CorrelationAnalysis::forward_returns(
    const Eigen::VectorXd& prices,
    int horizon) {

    int T = static_cast<int>(prices.size());
    int out_len = T - horizon;
    if (out_len <= 0) return Eigen::VectorXd();

    Eigen::VectorXd fwd(out_len);
    for (int t = 0; t < out_len; ++t) {
        double p0 = prices(t);
        double p1 = prices(t + horizon);
        fwd(t) = (p0 > 1e-15) ? (p1 / p0 - 1.0) : 0.0;
    }
    return fwd;
}

// ===========================================================================
// Pearson Information Coefficient (single cross-section)
// ===========================================================================

double CorrelationAnalysis::information_coefficient(
    const Eigen::VectorXd& factor_values,
    const Eigen::VectorXd& forward_returns) {

    int n = static_cast<int>(factor_values.size());
    if (n < 2 || n != static_cast<int>(forward_returns.size())) return 0.0;

    double mean_f = factor_values.mean();
    double mean_r = forward_returns.mean();

    Eigen::ArrayXd cf = factor_values.array() - mean_f;
    Eigen::ArrayXd cr = forward_returns.array() - mean_r;

    double cov = (cf * cr).sum();
    double var_f = cf.square().sum();
    double var_r = cr.square().sum();

    double denom = std::sqrt(var_f * var_r);
    return denom > 1e-15 ? cov / denom : 0.0;
}

// ===========================================================================
// Spearman Rank IC (single cross-section)
// ===========================================================================

double CorrelationAnalysis::rank_ic(
    const Eigen::VectorXd& factor_values,
    const Eigen::VectorXd& forward_returns) {

    // Convert both to ranks, then compute Pearson on ranks
    Eigen::VectorXd f_ranks = to_ranks(factor_values);
    Eigen::VectorXd r_ranks = to_ranks(forward_returns);
    return information_coefficient(f_ranks, r_ranks);
}

// ===========================================================================
// Two-sided t-test p-value for H0: mean = 0
// Uses the approximation: t = mean / (std / sqrt(n))
// P-value via the incomplete beta function approximation.
// ===========================================================================

namespace {

// Regularised incomplete beta function approximation using a continued fraction
// (Lentz's method). This is needed for the t-distribution CDF.
double betacf(double a, double b, double x) {
    constexpr int max_iter = 200;
    constexpr double eps = 3.0e-12;
    constexpr double fpmin = 1.0e-30;

    double qab = a + b;
    double qap = a + 1.0;
    double qam = a - 1.0;
    double c = 1.0;
    double d = 1.0 - qab * x / qap;
    if (std::abs(d) < fpmin) d = fpmin;
    d = 1.0 / d;
    double h = d;

    for (int m = 1; m <= max_iter; ++m) {
        double m2 = 2.0 * m;
        // Even step
        double aa = m * (b - m) * x / ((qam + m2) * (a + m2));
        d = 1.0 + aa * d;
        if (std::abs(d) < fpmin) d = fpmin;
        c = 1.0 + aa / c;
        if (std::abs(c) < fpmin) c = fpmin;
        d = 1.0 / d;
        h *= d * c;

        // Odd step
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2));
        d = 1.0 + aa * d;
        if (std::abs(d) < fpmin) d = fpmin;
        c = 1.0 + aa / c;
        if (std::abs(c) < fpmin) c = fpmin;
        d = 1.0 / d;
        double delta = d * c;
        h *= delta;
        if (std::abs(delta - 1.0) < eps) break;
    }
    return h;
}

// Log of the Beta function B(a, b) = Gamma(a)*Gamma(b)/Gamma(a+b)
double lbeta(double a, double b) {
    return std::lgamma(a) + std::lgamma(b) - std::lgamma(a + b);
}

// Regularised incomplete beta function I_x(a, b)
double betainc(double a, double b, double x) {
    if (x < 0.0 || x > 1.0) return 0.0;
    if (x < 1e-30) return 0.0;
    if (x > 1.0 - 1e-30) return 1.0;

    double bt = std::exp(
        a * std::log(x) + b * std::log(1.0 - x) - lbeta(a, b)
    );

    if (x < (a + 1.0) / (a + b + 2.0)) {
        return bt * betacf(a, b, x) / a;
    } else {
        return 1.0 - bt * betacf(b, a, 1.0 - x) / b;
    }
}

// CDF of Student's t-distribution with nu degrees of freedom
double t_cdf(double t_val, double nu) {
    double x = nu / (nu + t_val * t_val);
    double ib = betainc(0.5 * nu, 0.5, x);
    // For t_val >= 0, CDF = 1 - 0.5 * I_{x}(nu/2, 1/2)
    if (t_val >= 0) {
        return 1.0 - 0.5 * ib;
    } else {
        return 0.5 * ib;
    }
}

} // anonymous namespace

double CorrelationAnalysis::ttest_pvalue(const Eigen::VectorXd& sample) {
    int n = static_cast<int>(sample.size());
    if (n < 2) return 1.0;

    double mean = sample.mean();
    double var = (sample.array() - mean).square().sum() / static_cast<double>(n - 1);
    double se = std::sqrt(var / static_cast<double>(n));

    if (se < 1e-15) return (std::abs(mean) < 1e-15) ? 1.0 : 0.0;

    double t_stat = mean / se;
    double nu = static_cast<double>(n - 1);

    // Two-sided p-value = 2 * (1 - CDF(|t|))
    double p = 2.0 * (1.0 - t_cdf(std::abs(t_stat), nu));
    return std::min(std::max(p, 0.0), 1.0);
}

// ===========================================================================
// IC Summary -- aggregate IC stats over T cross-sections
// ===========================================================================

ICResult CorrelationAnalysis::ic_summary(
    const Eigen::MatrixXd& factor_panel,
    const Eigen::MatrixXd& return_panel,
    int horizon) {

    ICResult result;
    result.horizon = horizon;

    int N = static_cast<int>(factor_panel.rows());  // stocks
    int T = static_cast<int>(factor_panel.cols());   // dates

    if (N < 2 || T < 1) return result;
    if (factor_panel.rows() != return_panel.rows() ||
        factor_panel.cols() != return_panel.cols()) {
        return result;
    }

    Eigen::VectorXd ic_series(T);
    Eigen::VectorXd rank_ic_series(T);

    for (int t = 0; t < T; ++t) {
        Eigen::VectorXd fv = factor_panel.col(t);
        Eigen::VectorXd fr = return_panel.col(t);
        ic_series(t) = information_coefficient(fv, fr);
        rank_ic_series(t) = rank_ic(fv, fr);
    }

    result.n_periods = T;
    result.ic = ic_series.mean();
    result.rank_ic = rank_ic_series.mean();

    // IC standard deviation
    if (T >= 2) {
        double ic_var = (ic_series.array() - result.ic).square().sum()
                        / static_cast<double>(T - 1);
        result.ic_std = std::sqrt(ic_var);
    }

    // IC IR = mean(IC) / std(IC)
    result.ic_ir = result.ic_std > 1e-15 ? result.ic / result.ic_std : 0.0;

    // Rank IC IR
    if (T >= 2) {
        double ric_var = (rank_ic_series.array() - result.rank_ic).square().sum()
                         / static_cast<double>(T - 1);
        double ric_std = std::sqrt(ric_var);
        result.rank_ic_ir = ric_std > 1e-15 ? result.rank_ic / ric_std : 0.0;
    }

    // p-value from t-test on the IC series
    result.ic_pvalue = ttest_pvalue(ic_series);

    return result;
}

// ===========================================================================
// IC IR (convenience function)
// ===========================================================================

double CorrelationAnalysis::ic_ir(const Eigen::VectorXd& ic_series) {
    int n = static_cast<int>(ic_series.size());
    if (n < 2) return 0.0;

    double mean = ic_series.mean();
    double var = (ic_series.array() - mean).square().sum() / static_cast<double>(n - 1);
    double std_val = std::sqrt(var);
    return std_val > 1e-15 ? mean / std_val : 0.0;
}

// ===========================================================================
// IC Decay Profile
// ===========================================================================

ICDecayProfile CorrelationAnalysis::ic_decay(
    const Eigen::MatrixXd& factor_panel,
    const Eigen::MatrixXd& price_panel,
    const std::vector<int>& horizons,
    const std::string& factor_name) {

    ICDecayProfile profile;
    profile.factor_name = factor_name;

    int N = static_cast<int>(factor_panel.rows());  // stocks
    int T = static_cast<int>(factor_panel.cols());   // dates

    if (N < 2 || T < 2) return profile;
    if (price_panel.rows() != factor_panel.rows() ||
        price_panel.cols() != factor_panel.cols()) {
        return profile;
    }

    for (int h : horizons) {
        if (h <= 0 || h >= T) continue;

        // Build return panel: for each stock, compute forward returns at horizon h.
        // This reduces the number of usable dates to (T - h).
        int T_usable = T - h;
        if (T_usable < 1) continue;

        Eigen::MatrixXd fwd_return_panel(N, T_usable);
        for (int i = 0; i < N; ++i) {
            for (int t = 0; t < T_usable; ++t) {
                double p0 = price_panel(i, t);
                double p1 = price_panel(i, t + h);
                fwd_return_panel(i, t) = (p0 > 1e-15) ? (p1 / p0 - 1.0) : 0.0;
            }
        }

        // Trim factor panel to the same T_usable columns (starting columns)
        Eigen::MatrixXd trimmed_factor = factor_panel.leftCols(T_usable);

        ICResult ic_res = ic_summary(trimmed_factor, fwd_return_panel, h);
        profile.results.push_back(ic_res);
    }

    return profile;
}

// ===========================================================================
// Cross-factor Pearson correlation (N stocks x K factors -> K x K)
// ===========================================================================

Eigen::MatrixXd CorrelationAnalysis::cross_factor_correlation(
    const Eigen::MatrixXd& factor_matrix) {

    int N = static_cast<int>(factor_matrix.rows());  // stocks
    int K = static_cast<int>(factor_matrix.cols());   // factors

    if (K == 0 || N < 2) {
        return Eigen::MatrixXd::Identity(K, K);
    }

    // Center each column (factor)
    Eigen::MatrixXd centered = factor_matrix;
    for (int j = 0; j < K; ++j) {
        double col_mean = centered.col(j).mean();
        centered.col(j).array() -= col_mean;
    }

    // Covariance = centered^T * centered / (N - 1)
    Eigen::MatrixXd cov = (centered.transpose() * centered) / static_cast<double>(N - 1);

    // Convert to correlation
    Eigen::VectorXd std_devs = cov.diagonal().array().sqrt();
    Eigen::MatrixXd corr(K, K);
    for (int i = 0; i < K; ++i) {
        for (int j = 0; j < K; ++j) {
            double denom = std_devs(i) * std_devs(j);
            corr(i, j) = denom > 1e-15 ? cov(i, j) / denom : (i == j ? 1.0 : 0.0);
        }
    }

    return corr;
}

// ===========================================================================
// Cross-factor Spearman rank correlation
// ===========================================================================

Eigen::MatrixXd CorrelationAnalysis::cross_factor_rank_correlation(
    const Eigen::MatrixXd& factor_matrix) {

    int N = static_cast<int>(factor_matrix.rows());
    int K = static_cast<int>(factor_matrix.cols());

    if (K == 0 || N < 2) {
        return Eigen::MatrixXd::Identity(K, K);
    }

    // Convert each column to ranks, then compute Pearson on ranks
    Eigen::MatrixXd ranked(N, K);
    for (int j = 0; j < K; ++j) {
        ranked.col(j) = to_ranks(factor_matrix.col(j));
    }

    return cross_factor_correlation(ranked);
}

} // namespace trade
