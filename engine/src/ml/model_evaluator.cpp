#include "trade/ml/model_evaluator.h"
#include "trade/stats/correlation.h"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <random>
#include <vector>

namespace trade {

namespace {

// Standard normal CDF using erfc approximation
double normal_cdf(double x) {
    return 0.5 * std::erfc(-x / std::sqrt(2.0));
}

// Regularised incomplete beta continued fraction (Lentz's method)
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

// Log of the Beta function B(a, b)
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
    if (t_val >= 0) {
        return 1.0 - 0.5 * ib;
    } else {
        return 0.5 * ib;
    }
}

// Compute sample standard deviation (unbiased, ddof=1)
double sample_std(const Eigen::VectorXd& v) {
    int n = static_cast<int>(v.size());
    if (n < 2) return 0.0;
    double mean = v.mean();
    double var = (v.array() - mean).square().sum() / static_cast<double>(n - 1);
    return std::sqrt(var);
}

} // anonymous namespace

// ===========================================================================
// evaluate_ic: multi-horizon IC evaluation
// ===========================================================================

std::vector<HorizonICResult> ModelEvaluator::evaluate_ic(
    const Eigen::MatrixXd& predictions,
    const Eigen::MatrixXd& price_panel,
    const std::vector<int>& horizons) {

    std::vector<HorizonICResult> results;
    int N = static_cast<int>(price_panel.rows());
    int T = static_cast<int>(price_panel.cols());

    for (int h : horizons) {
        if (h <= 0 || h >= T) continue;

        int T_usable = T - h;
        if (T_usable < 1) continue;

        // Build forward returns panel: N x T_usable
        Eigen::MatrixXd fwd_returns(N, T_usable);
        for (int i = 0; i < N; ++i) {
            for (int t = 0; t < T_usable; ++t) {
                double p0 = price_panel(i, t);
                double p1 = price_panel(i, t + h);
                fwd_returns(i, t) = (p0 > 1e-15) ? (p1 / p0 - 1.0) : 0.0;
            }
        }

        // Trim predictions to match the usable dates
        Eigen::MatrixXd trimmed_preds = predictions.leftCols(T_usable);

        results.push_back(evaluate_ic_single(trimmed_preds, fwd_returns, h));
    }

    return results;
}

// ===========================================================================
// evaluate_ic_single: single-horizon IC from pre-computed forward returns
// ===========================================================================

HorizonICResult ModelEvaluator::evaluate_ic_single(
    const Eigen::MatrixXd& predictions,
    const Eigen::MatrixXd& forward_returns,
    int horizon) {

    HorizonICResult r;
    r.horizon = horizon;

    int T = static_cast<int>(predictions.cols());
    if (T < 1) return r;
    if (predictions.rows() != forward_returns.rows() ||
        predictions.cols() != forward_returns.cols()) {
        return r;
    }

    Eigen::VectorXd ic_series(T);
    Eigen::VectorXd rank_ic_series(T);

    for (int t = 0; t < T; ++t) {
        Eigen::VectorXd preds_col = predictions.col(t);
        Eigen::VectorXd rets_col = forward_returns.col(t);
        ic_series(t) = CorrelationAnalysis::information_coefficient(preds_col, rets_col);
        rank_ic_series(t) = CorrelationAnalysis::rank_ic(preds_col, rets_col);
    }

    r.n_periods = T;
    r.ic = ic_series.mean();
    r.rank_ic = rank_ic_series.mean();

    double ic_std_val = sample_std(ic_series);
    double rank_ic_std_val = sample_std(rank_ic_series);

    r.ic_ir = ic_std_val > 1e-15 ? r.ic / ic_std_val : 0.0;
    r.rank_ic_ir = rank_ic_std_val > 1e-15 ? r.rank_ic / rank_ic_std_val : 0.0;

    return r;
}

// ===========================================================================
// rank_features: combine gain, split, and SHAP importance; rank and sort
// ===========================================================================

std::vector<FeatureImportanceEntry> ModelEvaluator::rank_features(
    const Eigen::VectorXd& gain_importance,
    const Eigen::VectorXd& split_importance,
    const Eigen::MatrixXd& shap_matrix,
    const std::vector<std::string>& feature_names) {

    int K = static_cast<int>(feature_names.size());
    if (K == 0) return {};

    // Compute mean |SHAP| per feature
    Eigen::VectorXd shap_vals = Eigen::VectorXd::Zero(K);
    if (shap_matrix.rows() > 0 && shap_matrix.cols() == K) {
        shap_vals = mean_abs_shap(shap_matrix);
    }

    // Build entries
    std::vector<FeatureImportanceEntry> entries(K);
    for (int i = 0; i < K; ++i) {
        entries[i].name = feature_names[i];
        entries[i].gain_importance = (i < gain_importance.size()) ? gain_importance(i) : 0.0;
        entries[i].split_importance = (i < split_importance.size()) ? split_importance(i) : 0.0;
        entries[i].shap_mean_abs = shap_vals(i);
    }

    // Compute rank_gain: sort by gain descending, assign 1-indexed ranks
    {
        std::vector<int> indices(K);
        std::iota(indices.begin(), indices.end(), 0);
        std::sort(indices.begin(), indices.end(), [&](int a, int b) {
            return entries[a].gain_importance > entries[b].gain_importance;
        });
        for (int rank = 0; rank < K; ++rank) {
            entries[indices[rank]].rank_gain = rank + 1;
        }
    }

    // Compute rank_shap: sort by shap_mean_abs descending, assign 1-indexed ranks
    {
        std::vector<int> indices(K);
        std::iota(indices.begin(), indices.end(), 0);
        std::sort(indices.begin(), indices.end(), [&](int a, int b) {
            return entries[a].shap_mean_abs > entries[b].shap_mean_abs;
        });
        for (int rank = 0; rank < K; ++rank) {
            entries[indices[rank]].rank_shap = rank + 1;
        }
    }

    // Sort entries by gain descending
    std::sort(entries.begin(), entries.end(), [](const FeatureImportanceEntry& a,
                                                  const FeatureImportanceEntry& b) {
        return a.gain_importance > b.gain_importance;
    });

    return entries;
}

// ===========================================================================
// mean_abs_shap: per-feature mean absolute SHAP value
// ===========================================================================

Eigen::VectorXd ModelEvaluator::mean_abs_shap(const Eigen::MatrixXd& shap_matrix) {
    if (shap_matrix.cols() == 0) return {};
    return shap_matrix.cwiseAbs().colwise().mean();
}

// ===========================================================================
// top_k_shap: top K features by |SHAP| for a single prediction
// ===========================================================================

std::vector<std::pair<std::string, double>> ModelEvaluator::top_k_shap(
    const Eigen::VectorXd& shap_row,
    const std::vector<std::string>& feature_names,
    int k) {

    int n = static_cast<int>(shap_row.size());
    if (n == 0 || static_cast<int>(feature_names.size()) != n) return {};

    // Create index list sorted by |shap_value| descending
    std::vector<int> indices(n);
    std::iota(indices.begin(), indices.end(), 0);
    std::sort(indices.begin(), indices.end(), [&](int a, int b) {
        return std::abs(shap_row(a)) > std::abs(shap_row(b));
    });

    int count = std::min(k, n);
    std::vector<std::pair<std::string, double>> result;
    result.reserve(count);
    for (int i = 0; i < count; ++i) {
        int idx = indices[i];
        result.emplace_back(feature_names[idx], shap_row(idx));
    }

    return result;
}

// ===========================================================================
// calibration_curve: predicted probability vs actual frequency
// ===========================================================================

std::vector<CalibrationBin> ModelEvaluator::calibration_curve(
    const Eigen::VectorXd& predicted,
    const Eigen::VectorXd& actual,
    int n_bins) {

    int n = static_cast<int>(predicted.size());
    if (n == 0 || n != static_cast<int>(actual.size()) || n_bins <= 0) return {};

    std::vector<CalibrationBin> bins(n_bins);
    double bin_width = 1.0 / static_cast<double>(n_bins);

    // Initialize bin boundaries
    for (int b = 0; b < n_bins; ++b) {
        bins[b].pred_low = b * bin_width;
        bins[b].pred_high = (b + 1) * bin_width;
        bins[b].pred_mean = 0.0;
        bins[b].actual_freq = 0.0;
        bins[b].count = 0;
    }

    // Assign each sample to a bin
    for (int i = 0; i < n; ++i) {
        double p = predicted(i);
        int b = static_cast<int>(p / bin_width);
        // Clamp to valid range (handle p == 1.0 edge case)
        if (b >= n_bins) b = n_bins - 1;
        if (b < 0) b = 0;

        bins[b].pred_mean += p;
        bins[b].actual_freq += actual(i);
        bins[b].count += 1;
    }

    // Compute means
    for (int b = 0; b < n_bins; ++b) {
        if (bins[b].count > 0) {
            bins[b].pred_mean /= static_cast<double>(bins[b].count);
            bins[b].actual_freq /= static_cast<double>(bins[b].count);
        } else {
            // Empty bin: set pred_mean to bin center
            bins[b].pred_mean = (bins[b].pred_low + bins[b].pred_high) / 2.0;
            bins[b].actual_freq = 0.0;
        }
    }

    return bins;
}

// ===========================================================================
// brier_score: mean((predicted - actual)^2)
// ===========================================================================

double ModelEvaluator::brier_score(
    const Eigen::VectorXd& predicted,
    const Eigen::VectorXd& actual) {

    int n = static_cast<int>(predicted.size());
    if (n == 0 || n != static_cast<int>(actual.size())) return 0.0;

    return (predicted - actual).squaredNorm() / static_cast<double>(n);
}

// ===========================================================================
// sharpe_ratio: annualised Sharpe ratio from daily returns
// ===========================================================================

double ModelEvaluator::sharpe_ratio(
    const Eigen::VectorXd& returns,
    int trading_days_per_year) {

    int n = static_cast<int>(returns.size());
    if (n < 2) return 0.0;

    double mean = returns.mean();
    double var = (returns.array() - mean).square().sum() / static_cast<double>(n - 1);
    double std_val = std::sqrt(var);

    if (std_val < 1e-15) return 0.0;

    return (mean / std_val) * std::sqrt(static_cast<double>(trading_days_per_year));
}

// ===========================================================================
// skewness: Fisher's sample skewness
// ===========================================================================

double ModelEvaluator::skewness(const Eigen::VectorXd& data) {
    int n = static_cast<int>(data.size());
    if (n < 3) return 0.0;

    double mean = data.mean();
    double var = (data.array() - mean).square().sum() / static_cast<double>(n - 1);
    double std_val = std::sqrt(var);

    if (std_val < 1e-15) return 0.0;

    double m3 = ((data.array() - mean) / std_val).cube().sum();

    double nd = static_cast<double>(n);
    return (nd / ((nd - 1.0) * (nd - 2.0))) * m3;
}

// ===========================================================================
// kurtosis: excess kurtosis (Fisher's definition)
// ===========================================================================

double ModelEvaluator::kurtosis(const Eigen::VectorXd& data) {
    int n = static_cast<int>(data.size());
    if (n < 4) return 0.0;

    double mean = data.mean();
    double var = (data.array() - mean).square().sum() / static_cast<double>(n - 1);
    double std_val = std::sqrt(var);

    if (std_val < 1e-15) return 0.0;

    double m4 = ((data.array() - mean) / std_val).square().square().sum();

    double nd = static_cast<double>(n);
    double term1 = (nd * (nd + 1.0)) / ((nd - 1.0) * (nd - 2.0) * (nd - 3.0)) * m4;
    double term2 = (3.0 * (nd - 1.0) * (nd - 1.0)) / ((nd - 2.0) * (nd - 3.0));

    return term1 - term2;
}

// ===========================================================================
// expected_max_sharpe: E[max(SR)] under null of n_trials IID trials
// ===========================================================================

double ModelEvaluator::expected_max_sharpe(int n_trials) {
    if (n_trials <= 1) return 0.0;

    double N = static_cast<double>(n_trials);
    double log_N = std::log(N);

    if (log_N < 1e-15) return 0.0;

    double sqrt_2logN = std::sqrt(2.0 * log_N);
    double correction = (std::log(M_PI) + std::log(log_N)) / (2.0 * sqrt_2logN);

    return sqrt_2logN - correction;
}

// ===========================================================================
// deflated_sharpe_ratio: adjust SR for multiple testing
// ===========================================================================

DSRResult ModelEvaluator::deflated_sharpe_ratio(
    const Eigen::VectorXd& returns,
    int n_trials) {

    DSRResult result;
    result.n_trials = n_trials;

    int T = static_cast<int>(returns.size());
    if (T < 2) return result;

    // Compute annualized Sharpe (non-annualized for the DSR formula; use per-period SR)
    double mean_ret = returns.mean();
    double var_ret = (returns.array() - mean_ret).square().sum() / static_cast<double>(T - 1);
    double std_ret = std::sqrt(var_ret);

    if (std_ret < 1e-15) return result;

    double sr = mean_ret / std_ret;  // per-period Sharpe
    result.observed_sharpe = sr * std::sqrt(242.0);  // annualized for reporting

    // Skewness and kurtosis
    double skew = skewness(returns);
    double kurt = kurtosis(returns);

    // Expected max Sharpe under null
    double e_max_sr = expected_max_sharpe(n_trials);
    result.expected_max_sharpe = e_max_sr;

    // Variance of SR estimate: V(SR) = (1 - skew*SR + (kurt-1)/4 * SR^2) / (T-1)
    double v_sr = (1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr) / static_cast<double>(T - 1);

    if (v_sr <= 0.0) {
        result.dsr = 0.0;
        result.dsr_pvalue = 1.0;
        return result;
    }

    // DSR = (SR - E[max(SR)]) / sqrt(V(SR))
    double dsr = (sr - e_max_sr) / std::sqrt(v_sr);
    result.dsr = dsr;

    // p-value from standard normal CDF (one-sided)
    result.dsr_pvalue = 1.0 - normal_cdf(dsr);

    return result;
}

// ===========================================================================
// probability_of_backtest_overfitting (PBO via CSCV)
// ===========================================================================

PBOResult ModelEvaluator::probability_of_backtest_overfitting(
    const Eigen::MatrixXd& strategy_returns,
    int n_partitions) {

    PBOResult result;

    int T = static_cast<int>(strategy_returns.rows());  // periods
    int S = static_cast<int>(strategy_returns.cols());   // strategies

    if (T < n_partitions || S < 2 || n_partitions < 2) return result;

    // Ensure n_partitions is even
    if (n_partitions % 2 != 0) n_partitions -= 1;
    int half = n_partitions / 2;

    // Partition T periods into n_partitions roughly equal blocks
    int block_size = T / n_partitions;
    if (block_size < 1) return result;

    // Compute performance (Sharpe proxy: mean/std) per strategy per block
    // block_sharpes[b][s] = Sharpe of strategy s in block b
    std::vector<Eigen::VectorXd> block_sharpes(n_partitions);
    for (int b = 0; b < n_partitions; ++b) {
        int start = b * block_size;
        int end = (b == n_partitions - 1) ? T : (b + 1) * block_size;
        int len = end - start;

        block_sharpes[b].resize(S);
        for (int s = 0; s < S; ++s) {
            Eigen::VectorXd block_ret = strategy_returns.block(start, s, len, 1);
            double m = block_ret.mean();
            double var = (block_ret.array() - m).square().sum() / std::max(1.0, static_cast<double>(len - 1));
            double sd = std::sqrt(var);
            block_sharpes[b](s) = (sd > 1e-15) ? m / sd : 0.0;
        }
    }

    // Generate combinations of half blocks as in-sample
    // Use systematic enumeration but cap at a reasonable number
    // For n_partitions=16, half=8, C(16,8) = 12870 which is manageable
    // We enumerate using bitmask approach

    // Helper to enumerate all C(n_partitions, half) combinations
    // Each combination is represented as a bitmask
    std::vector<std::vector<int>> combinations;
    {
        // Generate all combinations of half elements from [0, n_partitions)
        std::vector<bool> selector(n_partitions, false);
        std::fill(selector.begin(), selector.begin() + half, true);

        // Sort to get first combination in lexicographic order via prev_permutation
        std::sort(selector.begin(), selector.end(), std::greater<bool>());

        do {
            std::vector<int> combo;
            for (int i = 0; i < n_partitions; ++i) {
                if (selector[i]) combo.push_back(i);
            }
            combinations.push_back(combo);
        } while (std::prev_permutation(selector.begin(), selector.end()));
    }

    // Cap combinations if too large (sample a subset)
    constexpr int max_combos = 5000;
    if (static_cast<int>(combinations.size()) > max_combos) {
        std::mt19937 rng(42);
        std::shuffle(combinations.begin(), combinations.end(), rng);
        combinations.resize(max_combos);
    }

    int n_overfit = 0;
    int n_combos = static_cast<int>(combinations.size());
    std::vector<double> logit_values;
    logit_values.reserve(n_combos);

    for (const auto& is_blocks : combinations) {
        // Determine OOS blocks
        std::vector<bool> is_in_sample(n_partitions, false);
        for (int b : is_blocks) is_in_sample[b] = true;

        std::vector<int> oos_blocks;
        for (int b = 0; b < n_partitions; ++b) {
            if (!is_in_sample[b]) oos_blocks.push_back(b);
        }

        // Compute IS and OOS Sharpe for each strategy
        Eigen::VectorXd is_sharpe(S);
        Eigen::VectorXd oos_sharpe(S);

        for (int s = 0; s < S; ++s) {
            double is_sum = 0.0;
            for (int b : is_blocks) is_sum += block_sharpes[b](s);
            is_sharpe(s) = is_sum / static_cast<double>(half);

            double oos_sum = 0.0;
            for (int b : oos_blocks) oos_sum += block_sharpes[b](s);
            oos_sharpe(s) = oos_sum / static_cast<double>(half);
        }

        // Find the strategy with best IS Sharpe
        int best_is = 0;
        double best_is_val = is_sharpe(0);
        for (int s = 1; s < S; ++s) {
            if (is_sharpe(s) > best_is_val) {
                best_is_val = is_sharpe(s);
                best_is = s;
            }
        }

        // Compute OOS rank of the IS-best strategy
        double best_oos_val = oos_sharpe(best_is);
        int rank_below = 0;  // count strategies with higher OOS sharpe
        for (int s = 0; s < S; ++s) {
            if (oos_sharpe(s) > best_oos_val) ++rank_below;
        }

        // Check if IS-best strategy ranks below median OOS
        // rank_below is the number of strategies that beat it OOS
        // If rank_below >= S/2, the IS-best is in the bottom half
        bool overfit = (rank_below >= S / 2);
        if (overfit) ++n_overfit;

        // Compute logit: w = OOS_rank / S, logit = log(w / (1 - w))
        // where OOS_rank is the relative position (higher = worse)
        double w = static_cast<double>(rank_below + 1) / static_cast<double>(S + 1);
        if (w <= 0.0) w = 1.0 / static_cast<double>(2 * (S + 1));
        if (w >= 1.0) w = 1.0 - 1.0 / static_cast<double>(2 * (S + 1));
        logit_values.push_back(std::log(w / (1.0 - w)));
    }

    result.n_combinations = n_combos;
    result.n_overfit = n_overfit;
    result.pbo = static_cast<double>(n_overfit) / static_cast<double>(n_combos);

    // Compute logit distribution stats
    if (!logit_values.empty()) {
        double sum = 0.0;
        for (double v : logit_values) sum += v;
        result.logit_mean = sum / static_cast<double>(logit_values.size());

        double var_sum = 0.0;
        for (double v : logit_values) {
            double diff = v - result.logit_mean;
            var_sum += diff * diff;
        }
        if (logit_values.size() > 1) {
            result.logit_std = std::sqrt(var_sum / static_cast<double>(logit_values.size() - 1));
        }
    }

    return result;
}

// ===========================================================================
// benjamini_hochberg: BH FDR correction
// ===========================================================================

FDRResult ModelEvaluator::benjamini_hochberg(
    const Eigen::VectorXd& p_values,
    double alpha) {

    FDRResult result;
    result.alpha = alpha;

    int n = static_cast<int>(p_values.size());
    result.total_tests = n;
    if (n == 0) return result;

    // Create sorted indices (ascending p-value)
    std::vector<int> sorted_indices(n);
    std::iota(sorted_indices.begin(), sorted_indices.end(), 0);
    std::sort(sorted_indices.begin(), sorted_indices.end(), [&](int a, int b) {
        return p_values(a) < p_values(b);
    });

    // Compute adjusted p-values
    std::vector<double> adjusted(n);
    for (int i = 0; i < n; ++i) {
        int rank = i + 1;  // 1-indexed rank
        int orig_idx = sorted_indices[i];
        adjusted[i] = p_values(orig_idx) * static_cast<double>(n) / static_cast<double>(rank);
    }

    // Enforce monotonicity: running min from right to left
    for (int i = n - 2; i >= 0; --i) {
        adjusted[i] = std::min(adjusted[i], adjusted[i + 1]);
    }

    // Cap at 1.0
    for (int i = 0; i < n; ++i) {
        adjusted[i] = std::min(adjusted[i], 1.0);
    }

    // Build entries (map back to original indices)
    result.entries.resize(n);
    for (int i = 0; i < n; ++i) {
        int orig_idx = sorted_indices[i];
        result.entries[i].index = orig_idx;
        result.entries[i].p_value = p_values(orig_idx);
        result.entries[i].adjusted_p = adjusted[i];
        result.entries[i].significant = (adjusted[i] <= alpha);
        if (result.entries[i].significant) ++result.significant_count;
    }

    // Sort entries by original index
    std::sort(result.entries.begin(), result.entries.end(),
              [](const FDRResult::Entry& a, const FDRResult::Entry& b) {
                  return a.index < b.index;
              });

    return result;
}

// ===========================================================================
// bootstrap_sharpe_ci: bootstrap confidence interval for Sharpe ratio
// ===========================================================================

BootstrapSharpeCI ModelEvaluator::bootstrap_sharpe_ci(
    const Eigen::VectorXd& returns,
    int n_bootstrap,
    double confidence,
    int seed) {

    BootstrapSharpeCI result;
    result.confidence_level = confidence;
    result.n_bootstrap = n_bootstrap;

    int T = static_cast<int>(returns.size());
    if (T < 2) return result;

    // Point estimate (non-annualized for consistency; use annualized)
    result.point_estimate = sharpe_ratio(returns);

    // Bootstrap resampling
    std::mt19937 rng(static_cast<unsigned>(seed));
    std::uniform_int_distribution<int> dist(0, T - 1);

    std::vector<double> bootstrap_sharpes(n_bootstrap);
    Eigen::VectorXd sample(T);

    for (int b = 0; b < n_bootstrap; ++b) {
        // Resample with replacement
        for (int i = 0; i < T; ++i) {
            sample(i) = returns(dist(rng));
        }
        bootstrap_sharpes[b] = sharpe_ratio(sample);
    }

    // Sort bootstrap Sharpes
    std::sort(bootstrap_sharpes.begin(), bootstrap_sharpes.end());

    // Extract percentiles
    double lower_pct = (1.0 - confidence) / 2.0;
    double upper_pct = 1.0 - lower_pct;

    int lower_idx = static_cast<int>(std::floor(lower_pct * static_cast<double>(n_bootstrap)));
    int upper_idx = static_cast<int>(std::floor(upper_pct * static_cast<double>(n_bootstrap)));

    lower_idx = std::max(0, std::min(lower_idx, n_bootstrap - 1));
    upper_idx = std::max(0, std::min(upper_idx, n_bootstrap - 1));

    result.ci_lower = bootstrap_sharpes[lower_idx];
    result.ci_upper = bootstrap_sharpes[upper_idx];

    return result;
}

// ===========================================================================
// full_evaluation: comprehensive evaluation report
// ===========================================================================

EvaluationReport ModelEvaluator::full_evaluation(
    const Eigen::MatrixXd& predictions,
    const Eigen::MatrixXd& price_panel,
    const Eigen::VectorXd& strategy_returns,
    const Eigen::VectorXd& gain_importance,
    const Eigen::VectorXd& split_importance,
    const Eigen::MatrixXd& shap_matrix,
    const std::vector<std::string>& feature_names,
    const std::vector<int>& horizons,
    int n_trials,
    const Eigen::MatrixXd& strategy_returns_matrix) {

    EvaluationReport report;

    // IC evaluation
    report.ic_results = evaluate_ic(predictions, price_panel, horizons);

    // Feature importance
    report.feature_importance = rank_features(gain_importance, split_importance,
                                               shap_matrix, feature_names);

    // DSR
    report.dsr = deflated_sharpe_ratio(strategy_returns, n_trials);

    // PBO (only if strategy_returns_matrix is non-empty)
    if (strategy_returns_matrix.rows() > 0 && strategy_returns_matrix.cols() > 0) {
        report.pbo = probability_of_backtest_overfitting(strategy_returns_matrix);
    }

    // Bootstrap Sharpe CI
    report.sharpe_ci = bootstrap_sharpe_ci(strategy_returns);

    // Summary
    if (!report.ic_results.empty()) {
        report.overall_rank_ic = report.ic_results[0].rank_ic;
        report.overall_ic_ir = report.ic_results[0].ic_ir;
    }

    report.passes_dsr_test = (report.dsr.dsr_pvalue < 0.05);
    report.passes_pbo_test = (report.pbo.pbo < 0.50);
    report.sharpe_ci_excludes_zero = (report.sharpe_ci.ci_lower > 0.0);

    return report;
}

} // namespace trade
