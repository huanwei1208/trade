#pragma once

#include "trade/backtest/backtest_engine.h"
#include "trade/backtest/performance.h"
#include "trade/backtest/strategy.h"
#include "trade/common/types.h"

#include <Eigen/Dense>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace trade {

// ============================================================================
// ValidationResult: output of the validation framework
// ============================================================================

struct FoldResult {
    int fold_index = 0;
    Date train_start;
    Date train_end;
    Date test_start;
    Date test_end;
    int train_days = 0;
    int test_days = 0;
    PerformanceReport train_perf;
    PerformanceReport test_perf;
    double train_sharpe = 0.0;
    double test_sharpe = 0.0;
    double overfit_ratio = 0.0;    // |train_sharpe - test_sharpe| / train_sharpe
};

struct OverfitTestResults {
    // Deflated Sharpe Ratio
    double dsr = 0.0;                  // DSR value
    bool dsr_pass = false;             // Pass if DSR > 0.95

    // Probability of Backtest Overfitting (CSCV method)
    double pbo = 0.0;                  // PBO value
    bool pbo_pass = false;             // Pass if PBO < 0.2

    // Minimum Backtest Length
    double mbl_years = 0.0;           // Minimum required years
    double actual_years = 0.0;        // Actual backtest length
    bool mbl_pass = false;             // Pass if actual >= mbl

    // Benjamini-Hochberg FDR
    double fdr = 0.0;                  // False Discovery Rate
    bool fdr_pass = false;             // Pass if FDR <= 0.05
    int num_rejected = 0;              // Number of rejected null hypotheses
    int num_trials = 0;                // Total number of trials

    // Bootstrap Sharpe CI
    double bootstrap_ci_lower = 0.0;
    double bootstrap_ci_upper = 0.0;
    bool bootstrap_pass = false;       // Pass if CI lower bound > 0

    // Overall
    bool all_pass() const {
        return dsr_pass && pbo_pass && mbl_pass && fdr_pass && bootstrap_pass;
    }

    int num_tests_passed() const {
        return static_cast<int>(dsr_pass) + static_cast<int>(pbo_pass) +
               static_cast<int>(mbl_pass) + static_cast<int>(fdr_pass) +
               static_cast<int>(bootstrap_pass);
    }
};

struct ValidationResult {
    std::string method;                         // "walk_forward" or "purged_kfold"
    std::vector<FoldResult> folds;
    OverfitTestResults overfit_tests;

    // Aggregate statistics across folds
    double mean_train_sharpe = 0.0;
    double mean_test_sharpe = 0.0;
    double std_test_sharpe = 0.0;
    double sharpe_decay = 0.0;                  // (train - test) / train
    double mean_overfit_ratio = 0.0;

    // Is the strategy considered valid?
    bool is_valid() const { return overfit_tests.all_pass(); }
};

// ============================================================================
// BacktestValidator: comprehensive validation framework
// ============================================================================
//
// Implements multiple validation methods to detect overfitting and ensure
// strategy robustness before deployment.
//
// 1. Walk-Forward Validation:
//    - Rolling window: 5 years training + 1 year test, 1 year step.
//    - No data leakage: test period is always strictly after training.
//    - Produces a sequence of out-of-sample performance metrics.
//
// 2. Purged K-Fold Cross-Validation:
//    - K=5 folds with purge gap and embargo to prevent leakage.
//    - Purge gap: prediction_horizon - 1 days between train and test.
//    - Embargo: max(5 days, 1% of training set size) after each test fold.
//    - Bidirectional: purge and embargo applied between ALL train-test
//      boundaries (both before and after each test fold).
//
// 3. Anti-Overfitting Tests:
//    - DSR (Deflated Sharpe Ratio): adjusts for multiple testing.
//      Pass criterion: DSR > 0.95.
//    - PBO (Probability of Backtest Overfitting): CSCV method.
//      Pass criterion: PBO < 0.2.
//    - MBL (Minimum Backtest Length): ensures sufficient data.
//      Based on Bailey et al. formula.
//    - Benjamini-Hochberg FDR: controls false discovery rate at 5%.
//    - Bootstrap Sharpe CI: 95% confidence interval lower bound > 0.
//

class BacktestValidator {
public:
    struct Config {
        // Walk-forward parameters
        int wf_train_years = 5;
        int wf_test_years = 1;
        int wf_step_years = 1;

        // Purged K-fold parameters
        int num_folds = 5;
        int prediction_horizon_days = 1;      // Purge gap = horizon - 1
        int min_embargo_days = 5;
        double embargo_pct = 0.01;            // 1% of training size

        // DSR parameters
        double dsr_threshold = 0.95;
        int dsr_num_trials = 1;               // Number of strategies tested

        // PBO parameters
        double pbo_threshold = 0.2;
        int pbo_num_subsets = 16;             // S in CSCV (must be even)

        // FDR parameters
        double fdr_threshold = 0.05;

        // Bootstrap parameters
        int bootstrap_samples = 10000;
        int bootstrap_block_size = 21;        // ~1 month
        double bootstrap_confidence = 0.95;

        // General
        bool verbose = false;
    };

    BacktestValidator(
        std::shared_ptr<IMarketDataFeed> market_data,
        std::shared_ptr<IExecutionVenue> execution,
        std::shared_ptr<IClock> clock);

    BacktestValidator(
        std::shared_ptr<IMarketDataFeed> market_data,
        std::shared_ptr<IExecutionVenue> execution,
        std::shared_ptr<IClock> clock,
        Config config);

    ~BacktestValidator();

    // -----------------------------------------------------------------------
    // Validation methods
    // -----------------------------------------------------------------------

    // Walk-forward validation with rolling windows.
    // Creates BacktestEngine internally for each fold.
    ValidationResult walk_forward(
        IStrategy& strategy,
        Date full_start,
        Date full_end,
        const BacktestEngine::Config& engine_config = {});

    // Purged K-fold cross-validation.
    // Applies purge gap and embargo between folds.
    ValidationResult purged_kfold(
        IStrategy& strategy,
        Date full_start,
        Date full_end,
        const BacktestEngine::Config& engine_config = {});

    // Run all validation methods and combine results.
    ValidationResult full_validation(
        IStrategy& strategy,
        Date full_start,
        Date full_end,
        const BacktestEngine::Config& engine_config = {});

    // -----------------------------------------------------------------------
    // Anti-overfitting tests (can be run independently)
    // -----------------------------------------------------------------------

    // Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014).
    // Adjusts observed Sharpe for the number of strategy variants tried.
    // observed_sharpe: the best Sharpe from all variants tested.
    // sharpe_estimates: Sharpe ratios of all variants (for variance estimation).
    double compute_dsr(
        double observed_sharpe,
        const std::vector<double>& sharpe_estimates,
        int num_observations) const;

    // Probability of Backtest Overfitting (Bailey et al., 2017).
    // Uses Combinatorially Symmetric Cross-Validation (CSCV).
    // Returns: probability that the best in-sample strategy is NOT the best
    //          out-of-sample (i.e., that we are overfitting).
    double compute_pbo(
        const Eigen::MatrixXd& returns_matrix,
        int num_subsets) const;

    // Minimum Backtest Length in years (Bailey et al., 2015).
    // Given a target Sharpe and number of trials, what's the minimum
    // backtest length needed for statistical significance?
    double compute_mbl(
        double target_sharpe,
        int num_trials,
        double skewness = 0.0,
        double kurtosis = 3.0) const;

    // Benjamini-Hochberg FDR procedure.
    // Given a set of p-values (one per strategy variant), determines which
    // strategies have statistically significant performance at the given FDR level.
    // Returns: number of rejected null hypotheses (significant strategies).
    struct FDRResult {
        int num_rejected = 0;
        double estimated_fdr = 0.0;
        std::vector<bool> rejected;   // Per-strategy: true if significant
    };
    FDRResult benjamini_hochberg(
        const std::vector<double>& p_values,
        double fdr_level = 0.05) const;

    // Run all overfit tests from fold results.
    OverfitTestResults run_overfit_tests(
        const std::vector<FoldResult>& folds,
        const std::vector<double>& daily_returns) const;

    // -----------------------------------------------------------------------
    // Accessors
    // -----------------------------------------------------------------------

    const Config& config() const { return config_; }

    // Callback for fold progress: (fold_index, total_folds)
    using ProgressCallback = std::function<void(int fold, int total)>;
    void set_progress_callback(ProgressCallback cb) { progress_cb_ = std::move(cb); }

private:
    // -----------------------------------------------------------------------
    // Fold construction helpers
    // -----------------------------------------------------------------------

    struct FoldSpec {
        Date train_start;
        Date train_end;
        Date test_start;
        Date test_end;
    };

    // Build walk-forward fold specifications.
    std::vector<FoldSpec> build_wf_folds(Date start, Date end) const;

    // Build purged K-fold specifications with embargo.
    std::vector<FoldSpec> build_purged_folds(
        const std::vector<Date>& all_trading_days) const;

    // Apply purge gap between train end and test start.
    Date apply_purge(Date boundary, int purge_days) const;

    // Apply embargo after test end into next training fold.
    Date apply_embargo(Date boundary, int embargo_days) const;

    // Compute embargo size: max(min_embargo_days, embargo_pct * train_size).
    int compute_embargo_size(int train_size) const;

    // Run a single fold and return FoldResult.
    FoldResult run_fold(
        int fold_index,
        const FoldSpec& spec,
        IStrategy& strategy,
        const BacktestEngine::Config& engine_config);

    // -----------------------------------------------------------------------
    // State
    // -----------------------------------------------------------------------

    Config config_;
    std::shared_ptr<IMarketDataFeed> market_data_;
    std::shared_ptr<IExecutionVenue> execution_;
    std::shared_ptr<IClock> clock_;
    PerformanceCalculator perf_calc_;
    ProgressCallback progress_cb_;
};

} // namespace trade
