#pragma once

#include "trade/common/types.h"
#include <Eigen/Dense>
#include <vector>
#include <string>
#include <unordered_map>

namespace trade {

// ---------------------------------------------------------------------------
// IC / Rank IC evaluation at a specific horizon
// ---------------------------------------------------------------------------
struct HorizonICResult {
    int horizon = 0;
    double ic = 0.0;
    double rank_ic = 0.0;
    double ic_ir = 0.0;
    double rank_ic_ir = 0.0;
    int n_periods = 0;
};

// ---------------------------------------------------------------------------
// Feature importance entry
// ---------------------------------------------------------------------------
struct FeatureImportanceEntry {
    std::string name;
    double gain_importance = 0.0;
    double split_importance = 0.0;
    double shap_mean_abs = 0.0;     // mean |SHAP| across samples
    int rank_gain = 0;
    int rank_shap = 0;
};

// ---------------------------------------------------------------------------
// Calibration bin (predicted probability vs actual frequency)
// ---------------------------------------------------------------------------
struct CalibrationBin {
    double pred_low = 0.0;          // lower bound of predicted probability bin
    double pred_high = 0.0;         // upper bound
    double pred_mean = 0.0;         // mean predicted value in this bin
    double actual_freq = 0.0;       // actual positive frequency in this bin
    int count = 0;                  // number of samples in this bin
};

// ---------------------------------------------------------------------------
// Deflated Sharpe Ratio result
// ---------------------------------------------------------------------------
struct DSRResult {
    double observed_sharpe = 0.0;
    double dsr = 0.0;              // deflated Sharpe ratio (haircut for trials)
    double dsr_pvalue = 0.0;       // p-value under the null
    int n_trials = 0;              // number of backtest trials considered
    double expected_max_sharpe = 0.0;  // E[max(SR)] under null of n_trials
};

// ---------------------------------------------------------------------------
// Probability of Backtest Overfitting result
// ---------------------------------------------------------------------------
struct PBOResult {
    double pbo = 0.0;              // probability of backtest overfitting [0, 1]
    int n_combinations = 0;        // number of train/test partition combos
    int n_overfit = 0;             // number of combos where IS-best underperforms OOS
    double logit_mean = 0.0;       // mean of the logit distribution
    double logit_std = 0.0;        // std of the logit distribution
};

// ---------------------------------------------------------------------------
// Bootstrap Sharpe CI result
// ---------------------------------------------------------------------------
struct BootstrapSharpeCI {
    double point_estimate = 0.0;   // original Sharpe ratio
    double ci_lower = 0.0;         // lower bound of CI
    double ci_upper = 0.0;         // upper bound of CI
    double confidence_level = 0.95;
    int n_bootstrap = 10000;
};

// ---------------------------------------------------------------------------
// Multiple testing correction result (Benjamini-Hochberg)
// ---------------------------------------------------------------------------
struct FDRResult {
    struct Entry {
        int index = 0;             // original index in the p-value vector
        double p_value = 0.0;
        double adjusted_p = 0.0;   // BH-adjusted p-value
        bool significant = false;  // significant at given alpha?
    };
    double alpha = 0.05;
    int total_tests = 0;
    int significant_count = 0;
    std::vector<Entry> entries;    // sorted by original index
};

// ---------------------------------------------------------------------------
// Full evaluation report
// ---------------------------------------------------------------------------
struct EvaluationReport {
    // IC metrics at multiple horizons
    std::vector<HorizonICResult> ic_results;

    // Feature importance
    std::vector<FeatureImportanceEntry> feature_importance;

    // Calibration
    std::vector<CalibrationBin> calibration;

    // Statistical tests
    DSRResult dsr;
    PBOResult pbo;
    BootstrapSharpeCI sharpe_ci;
    FDRResult fdr;

    // Summary
    double overall_rank_ic = 0.0;
    double overall_ic_ir = 0.0;
    bool passes_dsr_test = false;       // DSR p-value < 0.05
    bool passes_pbo_test = false;       // PBO < 0.50
    bool sharpe_ci_excludes_zero = false;
};

// ---------------------------------------------------------------------------
// ModelEvaluator: comprehensive model and strategy evaluation
// ---------------------------------------------------------------------------
class ModelEvaluator {
public:
    // ----- IC evaluation ---------------------------------------------------

    /// Compute IC and Rank IC across multiple forward horizons.
    /// @param predictions    N x T matrix (N stocks, T dates) of model predictions.
    /// @param price_panel    N x T matrix of prices (for computing forward returns).
    /// @param horizons       List of forward horizons (e.g., {1, 2, 5, 10, 20}).
    /// @return One HorizonICResult per horizon.
    static std::vector<HorizonICResult> evaluate_ic(
        const Eigen::MatrixXd& predictions,
        const Eigen::MatrixXd& price_panel,
        const std::vector<int>& horizons);

    /// Evaluate IC on a single horizon from pre-computed returns.
    static HorizonICResult evaluate_ic_single(
        const Eigen::MatrixXd& predictions,
        const Eigen::MatrixXd& forward_returns,
        int horizon);

    // ----- Feature importance ranking --------------------------------------

    /// Rank features by gain importance, split importance, and mean |SHAP|.
    /// @param gain_importance  K-vector of gain-based importance.
    /// @param split_importance K-vector of split-based importance.
    /// @param shap_matrix      M x K matrix of SHAP values (can be empty).
    /// @param feature_names    K feature names.
    /// @return Sorted (descending by gain) list of FeatureImportanceEntry.
    static std::vector<FeatureImportanceEntry> rank_features(
        const Eigen::VectorXd& gain_importance,
        const Eigen::VectorXd& split_importance,
        const Eigen::MatrixXd& shap_matrix,
        const std::vector<std::string>& feature_names);

    // ----- SHAP analysis ---------------------------------------------------

    /// Compute per-feature mean absolute SHAP value.
    /// @param shap_matrix  M x K SHAP value matrix.
    /// @return K-vector of mean |SHAP|.
    static Eigen::VectorXd mean_abs_shap(const Eigen::MatrixXd& shap_matrix);

    /// Top-K most impactful features for a single prediction.
    /// @param shap_row       K-vector of SHAP values for one sample.
    /// @param feature_names  Corresponding feature names.
    /// @param k              Number of top features to return.
    /// @return Top-K (name, shap_value) pairs sorted by |shap_value| descending.
    static std::vector<std::pair<std::string, double>> top_k_shap(
        const Eigen::VectorXd& shap_row,
        const std::vector<std::string>& feature_names,
        int k = 10);

    // ----- Calibration -----------------------------------------------------

    /// Compute calibration bins for predicted vs actual.
    /// @param predicted     N-vector of predicted probabilities.
    /// @param actual        N-vector of binary outcomes (0/1).
    /// @param n_bins        Number of bins (default 10).
    /// @return Vector of CalibrationBin.
    static std::vector<CalibrationBin> calibration_curve(
        const Eigen::VectorXd& predicted,
        const Eigen::VectorXd& actual,
        int n_bins = 10);

    /// Brier score = mean((predicted - actual)^2).
    static double brier_score(
        const Eigen::VectorXd& predicted,
        const Eigen::VectorXd& actual);

    // ----- Deflated Sharpe Ratio (DSR) -------------------------------------

    /// Compute the Deflated Sharpe Ratio.
    /// Adjusts observed Sharpe for the number of backtest trials, accounting
    /// for skewness and kurtosis of the return series.
    ///
    /// Reference: Bailey & Lopez de Prado (2014) "The Deflated Sharpe Ratio".
    ///
    /// @param returns     T-vector of strategy returns.
    /// @param n_trials    Number of backtest configurations tried.
    /// @return DSRResult with deflated Sharpe and p-value.
    static DSRResult deflated_sharpe_ratio(
        const Eigen::VectorXd& returns,
        int n_trials);

    /// Expected maximum Sharpe under the null (all trials have SR = 0).
    /// E[max(SR)] ~ sqrt(2 * log(n_trials)) - (log(pi) + log(log(n_trials))) /
    ///              (2 * sqrt(2 * log(n_trials)))
    static double expected_max_sharpe(int n_trials);

    // ----- Probability of Backtest Overfitting (PBO) -----------------------

    /// Compute PBO using the Combinatorially Symmetric Cross-Validation (CSCV)
    /// framework of Bailey et al. (2016).
    ///
    /// @param strategy_returns  T x S matrix (T periods, S strategies / param combos).
    /// @param n_partitions      Number of time-partitions (even, default 16).
    /// @return PBOResult with estimated probability of overfitting.
    static PBOResult probability_of_backtest_overfitting(
        const Eigen::MatrixXd& strategy_returns,
        int n_partitions = 16);

    // ----- Benjamini-Hochberg FDR ------------------------------------------

    /// Apply Benjamini-Hochberg False Discovery Rate correction.
    /// @param p_values  Vector of raw p-values from multiple tests.
    /// @param alpha     Significance threshold (default 0.05).
    /// @return FDRResult with adjusted p-values and significance flags.
    static FDRResult benjamini_hochberg(
        const Eigen::VectorXd& p_values,
        double alpha = 0.05);

    // ----- Bootstrap Sharpe CI ---------------------------------------------

    /// Bootstrap confidence interval for the Sharpe ratio.
    /// @param returns         T-vector of strategy returns.
    /// @param n_bootstrap     Number of bootstrap samples (default 10000).
    /// @param confidence      Confidence level (default 0.95).
    /// @param seed            RNG seed for reproducibility.
    /// @return BootstrapSharpeCI with point estimate and CI bounds.
    static BootstrapSharpeCI bootstrap_sharpe_ci(
        const Eigen::VectorXd& returns,
        int n_bootstrap = 10000,
        double confidence = 0.95,
        int seed = 42);

    // ----- Full evaluation report ------------------------------------------

    /// Run all evaluations and produce a comprehensive report.
    /// @param predictions     N x T prediction matrix.
    /// @param price_panel     N x T price matrix.
    /// @param strategy_returns T-vector of strategy daily returns.
    /// @param gain_importance K-vector of gain importance.
    /// @param split_importance K-vector of split importance.
    /// @param shap_matrix     M x K SHAP matrix (empty if unavailable).
    /// @param feature_names   K feature names.
    /// @param horizons        Forward horizons for IC evaluation.
    /// @param n_trials        Number of backtest trials (for DSR).
    /// @param strategy_returns_matrix  T x S matrix for PBO (empty to skip PBO).
    static EvaluationReport full_evaluation(
        const Eigen::MatrixXd& predictions,
        const Eigen::MatrixXd& price_panel,
        const Eigen::VectorXd& strategy_returns,
        const Eigen::VectorXd& gain_importance,
        const Eigen::VectorXd& split_importance,
        const Eigen::MatrixXd& shap_matrix,
        const std::vector<std::string>& feature_names,
        const std::vector<int>& horizons = {1, 2, 5, 10, 20},
        int n_trials = 1,
        const Eigen::MatrixXd& strategy_returns_matrix = Eigen::MatrixXd());

    // ----- Utilities -------------------------------------------------------

    /// Compute annualised Sharpe ratio from daily returns.
    static double sharpe_ratio(
        const Eigen::VectorXd& returns,
        int trading_days_per_year = 242);

    /// Compute sample skewness.
    static double skewness(const Eigen::VectorXd& data);

    /// Compute excess kurtosis.
    static double kurtosis(const Eigen::VectorXd& data);
};

} // namespace trade
