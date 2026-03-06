#include "trade/backtest/validation.h"
#include "trade/common/time_utils.h"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <random>

namespace trade {

// ---------------------------------------------------------------------------
// Helper: normal CDF (duplicated from performance.cpp for independence)
// ---------------------------------------------------------------------------
static double norm_cdf_val(double x) {
    const double a1 = 0.254829592;
    const double a2 = -0.284496736;
    const double a3 = 1.421413741;
    const double a4 = -1.453152027;
    const double a5 = 1.061405429;
    const double p  = 0.3275911;

    int sign = (x < 0) ? -1 : 1;
    x = std::abs(x) / std::sqrt(2.0);
    double t = 1.0 / (1.0 + p * x);
    double y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t
               * std::exp(-x * x);
    return 0.5 * (1.0 + sign * y);
}

// ---------------------------------------------------------------------------
// Constructor / Destructor
// ---------------------------------------------------------------------------

BacktestValidator::BacktestValidator(
    std::shared_ptr<IMarketDataFeed> market_data,
    std::shared_ptr<IExecutionVenue> execution,
    std::shared_ptr<IClock> clock)
    : config_{}
    , market_data_(std::move(market_data))
    , execution_(std::move(execution))
    , clock_(std::move(clock)) {}

BacktestValidator::BacktestValidator(
    std::shared_ptr<IMarketDataFeed> market_data,
    std::shared_ptr<IExecutionVenue> execution,
    std::shared_ptr<IClock> clock,
    Config config)
    : config_(std::move(config))
    , market_data_(std::move(market_data))
    , execution_(std::move(execution))
    , clock_(std::move(clock)) {}

BacktestValidator::~BacktestValidator() = default;

// ============================================================================
// Walk-Forward Validation
// ============================================================================
//
// Rolling window: 5 years training + 1 year test, 1 year step.
// No data leakage: test period is always strictly after training.
//

ValidationResult BacktestValidator::walk_forward(
    IStrategy& strategy, Date full_start, Date full_end,
    const BacktestEngine::Config& engine_config) {

    ValidationResult result;
    result.method = "walk_forward";

    // Build fold specifications
    auto fold_specs = build_wf_folds(full_start, full_end);
    if (fold_specs.empty()) return result;

    // Run each fold
    for (int i = 0; i < static_cast<int>(fold_specs.size()); ++i) {
        if (progress_cb_) {
            progress_cb_(i + 1, static_cast<int>(fold_specs.size()));
        }

        FoldResult fold = run_fold(i, fold_specs[i], strategy, engine_config);
        result.folds.push_back(fold);
    }

    // Compute aggregate statistics
    double sum_train_sharpe = 0.0;
    double sum_test_sharpe = 0.0;
    double sum_overfit = 0.0;
    std::vector<double> test_sharpes;

    for (const auto& fold : result.folds) {
        sum_train_sharpe += fold.train_sharpe;
        sum_test_sharpe += fold.test_sharpe;
        sum_overfit += fold.overfit_ratio;
        test_sharpes.push_back(fold.test_sharpe);
    }

    int n_folds = static_cast<int>(result.folds.size());
    result.mean_train_sharpe = n_folds > 0 ? sum_train_sharpe / n_folds : 0.0;
    result.mean_test_sharpe = n_folds > 0 ? sum_test_sharpe / n_folds : 0.0;
    result.mean_overfit_ratio = n_folds > 0 ? sum_overfit / n_folds : 0.0;

    // Standard deviation of test Sharpe
    if (n_folds > 1) {
        double mean = result.mean_test_sharpe;
        double sum_sq = 0.0;
        for (double s : test_sharpes) {
            double d = s - mean;
            sum_sq += d * d;
        }
        result.std_test_sharpe = std::sqrt(sum_sq / (n_folds - 1));
    }

    // Sharpe decay
    if (std::abs(result.mean_train_sharpe) > 1e-15) {
        result.sharpe_decay = (result.mean_train_sharpe - result.mean_test_sharpe)
                              / result.mean_train_sharpe;
    }

    // Run overfit tests using all test data
    // Collect all daily returns from test periods
    [[maybe_unused]] std::vector<double> all_daily_returns;
    for (const auto& fold : result.folds) {
        // Use test_sharpe as a proxy; in a full implementation we'd
        // aggregate actual daily returns from each fold's test period.
        // For now, we'll use the fold-level stats for overfit tests.
        (void)fold;
    }

    result.overfit_tests = run_overfit_tests(result.folds, test_sharpes);

    return result;
}

// ============================================================================
// Purged K-Fold Cross-Validation
// ============================================================================
//
// K=5 folds with purge gap and embargo to prevent data leakage.
// Purge gap: prediction_horizon - 1 days between train and test.
// Embargo: max(5 days, 1% of training set size) after each test fold.
//

ValidationResult BacktestValidator::purged_kfold(
    IStrategy& strategy, Date full_start, Date full_end,
    const BacktestEngine::Config& engine_config) {

    ValidationResult result;
    result.method = "purged_kfold";

    // Get all trading days in the period
    auto all_trading_days = clock_->trading_days_between(full_start, full_end);
    if (all_trading_days.empty()) return result;

    // Build purged fold specifications
    auto fold_specs = build_purged_folds(all_trading_days);
    if (fold_specs.empty()) return result;

    // Run each fold
    for (int i = 0; i < static_cast<int>(fold_specs.size()); ++i) {
        if (progress_cb_) {
            progress_cb_(i + 1, static_cast<int>(fold_specs.size()));
        }

        FoldResult fold = run_fold(i, fold_specs[i], strategy, engine_config);
        result.folds.push_back(fold);
    }

    // Compute aggregate statistics
    double sum_train_sharpe = 0.0;
    double sum_test_sharpe = 0.0;
    double sum_overfit = 0.0;
    std::vector<double> test_sharpes;

    for (const auto& fold : result.folds) {
        sum_train_sharpe += fold.train_sharpe;
        sum_test_sharpe += fold.test_sharpe;
        sum_overfit += fold.overfit_ratio;
        test_sharpes.push_back(fold.test_sharpe);
    }

    int n_folds = static_cast<int>(result.folds.size());
    result.mean_train_sharpe = n_folds > 0 ? sum_train_sharpe / n_folds : 0.0;
    result.mean_test_sharpe = n_folds > 0 ? sum_test_sharpe / n_folds : 0.0;
    result.mean_overfit_ratio = n_folds > 0 ? sum_overfit / n_folds : 0.0;

    if (n_folds > 1) {
        double mean = result.mean_test_sharpe;
        double sum_sq = 0.0;
        for (double s : test_sharpes) {
            double d = s - mean;
            sum_sq += d * d;
        }
        result.std_test_sharpe = std::sqrt(sum_sq / (n_folds - 1));
    }

    if (std::abs(result.mean_train_sharpe) > 1e-15) {
        result.sharpe_decay = (result.mean_train_sharpe - result.mean_test_sharpe)
                              / result.mean_train_sharpe;
    }

    result.overfit_tests = run_overfit_tests(result.folds, test_sharpes);

    return result;
}

// ============================================================================
// Full Validation (combined walk-forward + purged K-fold)
// ============================================================================

ValidationResult BacktestValidator::full_validation(
    IStrategy& strategy, Date full_start, Date full_end,
    const BacktestEngine::Config& engine_config) {

    // Run walk-forward as the primary method
    auto wf_result = walk_forward(strategy, full_start, full_end,
                                   engine_config);

    // Run purged K-fold as supplementary check
    auto kfold_result = purged_kfold(strategy, full_start, full_end,
                                      engine_config);

    // Combine: use walk-forward as primary result, augment with K-fold info
    // Take the more conservative overfit test results
    auto& ot = wf_result.overfit_tests;
    const auto& kot = kfold_result.overfit_tests;

    // Use the more conservative (worse) result for each test
    if (kot.dsr < ot.dsr) ot.dsr = kot.dsr;
    if (kot.pbo > ot.pbo) ot.pbo = kot.pbo;
    ot.dsr_pass = ot.dsr > config_.dsr_threshold;
    ot.pbo_pass = ot.pbo < config_.pbo_threshold;

    return wf_result;
}

// ============================================================================
// Deflated Sharpe Ratio (DSR)
// ============================================================================

double BacktestValidator::compute_dsr(
    double observed_sharpe,
    const std::vector<double>& sharpe_estimates,
    int num_observations) const {

    if (sharpe_estimates.empty() || num_observations < 2) return 0.0;

    int num_trials = static_cast<int>(sharpe_estimates.size());
    double n = static_cast<double>(num_observations);
    [[maybe_unused]] double gamma_em = 0.5772156649015329;  // Euler-Mascheroni constant

    // Compute variance of Sharpe estimates
    double mean_sr = 0.0;
    for (double s : sharpe_estimates) mean_sr += s;
    mean_sr /= sharpe_estimates.size();

    double var_sr = 0.0;
    for (double s : sharpe_estimates) {
        double d = s - mean_sr;
        var_sr += d * d;
    }
    var_sr /= std::max(1.0, static_cast<double>(sharpe_estimates.size() - 1));
    double std_sr = std::sqrt(var_sr);

    // Expected maximum Sharpe from num_trials
    double expected_max_sr = 0.0;
    if (num_trials > 1 && std_sr > 1e-15) {
        double ln_k = std::log(static_cast<double>(num_trials));
        if (ln_k > 0.0) {
            expected_max_sr = std_sr * (
                std::sqrt(2.0 * ln_k)
                - (std::log(std::log(static_cast<double>(num_trials)))
                   + std::log(4.0 * M_PI))
                  / (2.0 * std::sqrt(2.0 * ln_k))
            );
        }
    }

    // Standard error of Sharpe ratio
    double se = std::sqrt(1.0 / n);  // Simplified SE

    if (se < 1e-15) return 0.0;

    // DSR = Prob(SR* > observed | H0: true SR = expected_max)
    double z = (observed_sharpe - expected_max_sr) / se;
    return norm_cdf_val(z);
}

// ============================================================================
// Probability of Backtest Overfitting (PBO)
// ============================================================================
//
// CSCV method (Bailey et al., 2017):
// 1. Split returns_matrix columns (strategies) into S subsets.
// 2. For each of C(S, S/2) combinations:
//    a. Use half the subsets as "in-sample", half as "out-of-sample".
//    b. Find the best strategy in-sample.
//    c. Check its rank out-of-sample.
//    d. If the best IS strategy ranks below median OOS, that's an overfit.
// 3. PBO = fraction of combinations where overfitting is detected.
//

double BacktestValidator::compute_pbo(
    const Eigen::MatrixXd& returns_matrix,
    int num_subsets) const {

    int T = static_cast<int>(returns_matrix.rows());  // Time periods
    int N = static_cast<int>(returns_matrix.cols());  // Strategies

    if (T < 2 || N < 2 || num_subsets < 2) return 0.0;

    // Ensure num_subsets is even
    if (num_subsets % 2 != 0) num_subsets += 1;
    int half_s = num_subsets / 2;

    // Partition time periods into num_subsets groups
    int group_size = T / num_subsets;
    if (group_size < 1) return 0.0;

    // Compute Sharpe ratios for each strategy in each subset
    // subset_sharpes[s][n] = Sharpe of strategy n in subset s
    Eigen::MatrixXd subset_sharpes(num_subsets, N);
    for (int s = 0; s < num_subsets; ++s) {
        int start = s * group_size;
        int end = (s == num_subsets - 1) ? T : (s + 1) * group_size;
        int len = end - start;

        for (int n = 0; n < N; ++n) {
            // Compute Sharpe for strategy n in subset [start, end)
            double sum = 0.0;
            for (int t = start; t < end; ++t) {
                sum += returns_matrix(t, n);
            }
            double mean = sum / len;

            double sum_sq = 0.0;
            for (int t = start; t < end; ++t) {
                double d = returns_matrix(t, n) - mean;
                sum_sq += d * d;
            }
            double std_dev = std::sqrt(sum_sq / std::max(1, len - 1));
            subset_sharpes(s, n) = std_dev > 1e-15 ? mean / std_dev : 0.0;
        }
    }

    // Use random sampling of combinations (full enumeration is expensive)
    std::mt19937 rng(42);
    int max_combos = 1000;  // Sample up to 1000 combinations

    // Generate indices 0..num_subsets-1
    std::vector<int> indices(num_subsets);
    std::iota(indices.begin(), indices.end(), 0);

    int overfit_count = 0;
    int total_combos = 0;

    for (int c = 0; c < max_combos; ++c) {
        // Shuffle and take first half as IS, second half as OOS
        std::shuffle(indices.begin(), indices.end(), rng);

        // Compute combined Sharpe for IS and OOS
        Eigen::VectorXd is_sharpe = Eigen::VectorXd::Zero(N);
        Eigen::VectorXd oos_sharpe = Eigen::VectorXd::Zero(N);

        for (int i = 0; i < half_s; ++i) {
            for (int n = 0; n < N; ++n) {
                is_sharpe(n) += subset_sharpes(indices[i], n);
            }
        }
        for (int i = half_s; i < num_subsets; ++i) {
            for (int n = 0; n < N; ++n) {
                oos_sharpe(n) += subset_sharpes(indices[i], n);
            }
        }

        // Average across subsets
        is_sharpe /= half_s;
        oos_sharpe /= (num_subsets - half_s);

        // Find best IS strategy
        int best_is = 0;
        double best_is_sharpe = is_sharpe(0);
        for (int n = 1; n < N; ++n) {
            if (is_sharpe(n) > best_is_sharpe) {
                best_is_sharpe = is_sharpe(n);
                best_is = n;
            }
        }

        // Check rank of best-IS strategy in OOS
        double best_is_oos = oos_sharpe(best_is);
        int rank_below = 0;
        for (int n = 0; n < N; ++n) {
            if (oos_sharpe(n) > best_is_oos) ++rank_below;
        }

        // If more than half the strategies beat it OOS, it's overfitting
        if (rank_below >= N / 2) {
            ++overfit_count;
        }
        ++total_combos;
    }

    return total_combos > 0
           ? static_cast<double>(overfit_count) / total_combos
           : 0.0;
}

// ============================================================================
// Minimum Backtest Length (MBL)
// ============================================================================

double BacktestValidator::compute_mbl(
    double target_sharpe, int num_trials,
    double skewness, double kurtosis) const {

    if (target_sharpe <= 0.0 || num_trials <= 0) return 0.0;

    // MBL formula from Bailey et al. (2015):
    // MinBL = (1 + (1 - skew * SR + (kurtosis - 1)/4 * SR^2)) *
    //         (Z_alpha / SR)^2
    //
    // Where Z_alpha comes from the expected max Sharpe given num_trials.
    // Simplified: we use the Bonferroni correction approach.

    [[maybe_unused]] double gamma_em = 0.5772156649015329;
    double sr = target_sharpe / std::sqrt(252.0);  // De-annualise

    // Expected max Sharpe from num_trials
    double z_alpha;
    if (num_trials > 1) {
        double ln_k = std::log(static_cast<double>(num_trials));
        z_alpha = std::sqrt(2.0 * ln_k)
                  - (std::log(std::log(static_cast<double>(num_trials)))
                     + std::log(4.0 * M_PI))
                    / (2.0 * std::sqrt(2.0 * ln_k));
    } else {
        z_alpha = 1.96;  // 95% confidence for single trial
    }

    // Correction factor for non-normal returns
    double correction = 1.0
        + (1.0 - skewness * sr + (kurtosis - 1.0) / 4.0 * sr * sr);

    // MinBL in observations (trading days)
    double mbl_days = correction * std::pow(z_alpha / sr, 2.0);

    // Convert to years
    return mbl_days / 252.0;
}

// ============================================================================
// Benjamini-Hochberg FDR Procedure
// ============================================================================

BacktestValidator::FDRResult BacktestValidator::benjamini_hochberg(
    const std::vector<double>& p_values,
    double fdr_level) const {

    FDRResult result;
    int m = static_cast<int>(p_values.size());
    if (m == 0) return result;

    // Sort p-values while keeping track of original indices
    std::vector<std::pair<double, int>> sorted_p;
    sorted_p.reserve(m);
    for (int i = 0; i < m; ++i) {
        sorted_p.emplace_back(p_values[i], i);
    }
    std::sort(sorted_p.begin(), sorted_p.end());

    // BH procedure: find largest k such that p_(k) <= k/m * fdr_level
    result.rejected.resize(m, false);
    int largest_k = -1;

    for (int k = 0; k < m; ++k) {
        double threshold = static_cast<double>(k + 1) / m * fdr_level;
        if (sorted_p[k].first <= threshold) {
            largest_k = k;
        }
    }

    // Reject all hypotheses with rank <= largest_k
    if (largest_k >= 0) {
        for (int k = 0; k <= largest_k; ++k) {
            result.rejected[sorted_p[k].second] = true;
            ++result.num_rejected;
        }
    }

    // Estimate FDR
    result.estimated_fdr = result.num_rejected > 0
        ? static_cast<double>(m) * sorted_p[largest_k].first
          / result.num_rejected
        : 0.0;

    return result;
}

// ============================================================================
// Run all overfit tests from fold results
// ============================================================================

OverfitTestResults BacktestValidator::run_overfit_tests(
    const std::vector<FoldResult>& folds,
    const std::vector<double>& daily_returns) const {

    OverfitTestResults results;
    if (folds.empty()) return results;

    int n_folds = static_cast<int>(folds.size());

    // Collect Sharpe estimates from all folds
    std::vector<double> train_sharpes, test_sharpes;
    for (const auto& fold : folds) {
        train_sharpes.push_back(fold.train_sharpe);
        test_sharpes.push_back(fold.test_sharpe);
    }

    // --------------------------------------------------
    // 1. Deflated Sharpe Ratio
    // --------------------------------------------------
    double best_sharpe = *std::max_element(test_sharpes.begin(),
                                            test_sharpes.end());
    // Approximate num_observations from fold days
    int total_test_days = 0;
    for (const auto& fold : folds) {
        total_test_days += fold.test_days;
    }
    int num_observations = std::max(total_test_days, 252);

    results.dsr = compute_dsr(best_sharpe, test_sharpes, num_observations);
    results.dsr_pass = results.dsr > config_.dsr_threshold;

    // --------------------------------------------------
    // 2. PBO (simplified version using fold Sharpes)
    // --------------------------------------------------
    // For a proper PBO, we need a returns matrix of multiple strategies.
    // With a single strategy, we approximate PBO from train/test Sharpe decay.
    // PBO ~ fraction of folds where test Sharpe < 0 or test << train
    int overfit_folds = 0;
    for (const auto& fold : folds) {
        // A fold shows overfitting if the test Sharpe is substantially
        // worse than the train Sharpe
        if (fold.test_sharpe < 0.0 ||
            (fold.train_sharpe > 0.5 && fold.overfit_ratio > 0.5)) {
            ++overfit_folds;
        }
    }
    results.pbo = static_cast<double>(overfit_folds) / n_folds;
    results.pbo_pass = results.pbo < config_.pbo_threshold;

    // --------------------------------------------------
    // 3. Minimum Backtest Length
    // --------------------------------------------------
    double target_sharpe = best_sharpe > 0.0 ? best_sharpe : 0.5;
    results.mbl_years = compute_mbl(target_sharpe, config_.dsr_num_trials,
                                     0.0, 3.0);

    // Compute actual backtest length
    if (!folds.empty()) {
        auto first_start = folds.front().train_start;
        auto last_end = folds.back().test_end;
        double actual_days = static_cast<double>((last_end - first_start).count());
        results.actual_years = actual_days / 365.25;
    }
    results.mbl_pass = results.actual_years >= results.mbl_years;

    // --------------------------------------------------
    // 4. Benjamini-Hochberg FDR
    // --------------------------------------------------
    // Compute p-values from test Sharpe ratios
    std::vector<double> p_values;
    for (double sr : test_sharpes) {
        // One-sided p-value: P(SR > observed | H0: SR = 0)
        // Using t-statistic approximation
        double se = 1.0 / std::sqrt(std::max(1.0,
                                              static_cast<double>(num_observations)));
        double t_stat = sr / std::max(se, 1e-15);
        double p_val = 1.0 - norm_cdf_val(t_stat);
        p_values.push_back(p_val);
    }

    auto fdr_result = benjamini_hochberg(p_values, config_.fdr_threshold);
    results.fdr = fdr_result.estimated_fdr;
    results.fdr_pass = results.fdr <= config_.fdr_threshold;
    results.num_rejected = fdr_result.num_rejected;
    results.num_trials = n_folds;

    // --------------------------------------------------
    // 5. Bootstrap Sharpe CI
    // --------------------------------------------------
    // If we have actual daily returns, bootstrap the CI
    if (!daily_returns.empty() && daily_returns.size() > 10) {
        PerformanceCalculator perf_calc;
        auto ci = perf_calc.bootstrap_sharpe_ci(daily_returns, 0.95);
        results.bootstrap_ci_lower = ci.first;
        results.bootstrap_ci_upper = ci.second;
        results.bootstrap_pass = ci.first > 0.0;
    } else {
        // Use test Sharpe distribution as proxy
        double mean_test = 0.0;
        for (double s : test_sharpes) mean_test += s;
        mean_test /= n_folds;

        double std_test = 0.0;
        for (double s : test_sharpes) {
            double d = s - mean_test;
            std_test += d * d;
        }
        std_test = std::sqrt(std_test / std::max(1, n_folds - 1));

        results.bootstrap_ci_lower = mean_test - 1.96 * std_test;
        results.bootstrap_ci_upper = mean_test + 1.96 * std_test;
        results.bootstrap_pass = results.bootstrap_ci_lower > 0.0;
    }

    return results;
}

// ============================================================================
// Fold construction helpers
// ============================================================================

std::vector<BacktestValidator::FoldSpec>
BacktestValidator::build_wf_folds(Date start, Date end) const {
    std::vector<FoldSpec> folds;

    // Duration in calendar days
    auto total_days = (end - start).count();
    if (total_days <= 0) return folds;

    // Convert years to approximate calendar days
    int train_days = config_.wf_train_years * 365;
    int test_days = config_.wf_test_years * 365;
    int step_days = config_.wf_step_years * 365;

    // Build rolling windows
    Date current_train_start = start;

    while (true) {
        Date train_end = current_train_start
                        + std::chrono::days(train_days);
        Date test_start = train_end + std::chrono::days(1);
        Date test_end = test_start
                       + std::chrono::days(test_days - 1);

        // Ensure test_end doesn't exceed the full end date
        if (test_end > end) {
            test_end = end;
        }

        // Need at least some test data
        if (test_start >= end) break;

        FoldSpec spec;
        spec.train_start = current_train_start;
        spec.train_end = train_end;
        spec.test_start = test_start;
        spec.test_end = test_end;
        folds.push_back(spec);

        // Step forward
        current_train_start += std::chrono::days(step_days);
    }

    return folds;
}

std::vector<BacktestValidator::FoldSpec>
BacktestValidator::build_purged_folds(
    const std::vector<Date>& all_trading_days) const {
    std::vector<FoldSpec> folds;

    int n = static_cast<int>(all_trading_days.size());
    int k = config_.num_folds;
    if (n < k * 10) return folds;  // Need enough data for meaningful folds

    int fold_size = n / k;

    for (int fold_idx = 0; fold_idx < k; ++fold_idx) {
        // Test fold: indices [fold_start, fold_end)
        int test_start_idx = fold_idx * fold_size;
        int test_end_idx = (fold_idx == k - 1) ? n - 1
                           : (fold_idx + 1) * fold_size - 1;

        // Compute purge and embargo sizes
        int purge_days = std::max(0, config_.prediction_horizon_days - 1);
        int train_size = n - (test_end_idx - test_start_idx + 1);
        int embargo_size = compute_embargo_size(train_size);

        // Train period: all days except test + purge + embargo
        // Apply purge before test start
        int purged_train_end_idx = std::max(0, test_start_idx - purge_days - 1);

        // Apply embargo after test end
        [[maybe_unused]] int embargoed_train_start_idx = std::min(n - 1,
                                                  test_end_idx + embargo_size + 1);

        // For K-fold: train is everything outside [test_start - purge, test_end + embargo]
        // We'll define train as the period before test (with purge) since
        // using data after the test period would violate temporal ordering
        // for time-series cross-validation.

        // Use only pre-test data for training (expanding window approach)
        if (purged_train_end_idx <= 0) continue;  // Not enough pre-test data

        FoldSpec spec;
        spec.train_start = all_trading_days[0];
        spec.train_end = all_trading_days[purged_train_end_idx];
        spec.test_start = all_trading_days[test_start_idx];
        spec.test_end = all_trading_days[test_end_idx];

        folds.push_back(spec);
    }

    return folds;
}

Date BacktestValidator::apply_purge(Date boundary, int purge_days) const {
    return boundary + std::chrono::days(purge_days);
}

Date BacktestValidator::apply_embargo(Date boundary, int embargo_days) const {
    return boundary + std::chrono::days(embargo_days);
}

int BacktestValidator::compute_embargo_size(int train_size) const {
    return std::max(config_.min_embargo_days,
                    static_cast<int>(config_.embargo_pct * train_size));
}

// ============================================================================
// Run a single fold
// ============================================================================

FoldResult BacktestValidator::run_fold(
    int fold_index, const FoldSpec& spec, IStrategy& strategy,
    const BacktestEngine::Config& engine_config) {

    FoldResult result;
    result.fold_index = fold_index;
    result.train_start = spec.train_start;
    result.train_end = spec.train_end;
    result.test_start = spec.test_start;
    result.test_end = spec.test_end;

    // --- Run training period backtest ---
    {
        BacktestEngine train_engine(market_data_, execution_, clock_,
                                     engine_config);
        BacktestResult train_result = train_engine.run(strategy,
                                                        spec.train_start,
                                                        spec.train_end);

        result.train_days = train_result.trading_days;
        result.train_perf = perf_calc_.compute(train_result);
        result.train_sharpe = result.train_perf.sharpe_ratio;
    }

    // --- Run test period backtest ---
    {
        BacktestEngine test_engine(market_data_, execution_, clock_,
                                    engine_config);
        BacktestResult test_result = test_engine.run(strategy,
                                                      spec.test_start,
                                                      spec.test_end);

        result.test_days = test_result.trading_days;
        result.test_perf = perf_calc_.compute(test_result);
        result.test_sharpe = result.test_perf.sharpe_ratio;
    }

    // Compute overfit ratio
    if (std::abs(result.train_sharpe) > 1e-15) {
        result.overfit_ratio = std::abs(result.train_sharpe - result.test_sharpe)
                               / std::abs(result.train_sharpe);
    }

    return result;
}

} // namespace trade
