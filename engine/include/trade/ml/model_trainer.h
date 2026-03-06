#pragma once

#include "trade/common/types.h"
#include "trade/ml/lgbm_model.h"
#include <Eigen/Dense>
#include <vector>
#include <string>
#include <functional>
#include <optional>
#include <memory>

namespace trade {

// ---------------------------------------------------------------------------
// Data split indices: train / validation / test
// ---------------------------------------------------------------------------
struct SplitIndices {
    std::vector<int> train;     // row indices into the full dataset
    std::vector<int> valid;     // validation (for early stopping)
    std::vector<int> test;      // held-out test
};

// ---------------------------------------------------------------------------
// Walk-forward or CV fold descriptor
// ---------------------------------------------------------------------------
struct FoldSpec {
    int fold_id = 0;
    Date train_start;
    Date train_end;
    Date valid_start;           // purged gap lives between train_end and valid_start
    Date valid_end;
    Date embargo_end;           // embargo period after valid_end (excluded from next fold train)
    SplitIndices indices;
};

#ifdef HAVE_LIGHTGBM
// ---------------------------------------------------------------------------
// Trained fold result
// ---------------------------------------------------------------------------
struct FoldResult {
    int fold_id = 0;
    LGBMTrainResult train_result;
    double test_ic = 0.0;
    double test_rank_ic = 0.0;
    double test_mse = 0.0;
    double test_mae = 0.0;
    Eigen::VectorXd predictions;   // predictions on the test set
    Eigen::VectorXd actuals;       // actual values on the test set
};

// ---------------------------------------------------------------------------
// Full pipeline result
// ---------------------------------------------------------------------------
struct TrainingPipelineResult {
    std::vector<FoldResult> fold_results;
    double mean_test_ic = 0.0;
    double mean_test_rank_ic = 0.0;
    double std_test_ic = 0.0;
    std::string best_model_path;       // path to the saved best model
    int best_fold_id = -1;
    LGBMParams best_params;
};
#endif // HAVE_LIGHTGBM

// ---------------------------------------------------------------------------
// ModelTrainer: orchestrates time-series-aware training and validation
// ---------------------------------------------------------------------------
class ModelTrainer {
public:
    // ----- Configuration ---------------------------------------------------

    struct Config {
        // Walk-forward parameters
        int train_years = 5;            // training window length (years)
        int test_years = 1;             // test window length (years)
        int step_years = 1;             // step between successive folds

        // Purged K-fold CV parameters
        int n_folds = 5;
        int prediction_horizon = 5;     // forward return horizon in trading days
        int purge_gap = -1;             // default = prediction_horizon - 1
        int embargo_days = -1;          // default = max(5, floor(0.01 * train_size))

        // Model output
        std::string model_output_dir = "models";
        std::string model_name_prefix = "lgbm";

        // Feature / label column names (optional, for logging/metadata)
        std::vector<std::string> feature_names;
        std::string label_name = "fwd_return";

        /// Resolve defaults for purge_gap and embargo_days given train size.
        void resolve_defaults(int train_size);
    };

    explicit ModelTrainer(Config config);

    // ----- Split generation ------------------------------------------------

    /// Generate Walk-Forward validation folds.
    /// @param dates       Sorted vector of all trading dates in the dataset.
    /// @param date_index  Map from Date to row-index in the feature matrix.
    /// @return Ordered list of FoldSpec for walk-forward evaluation.
    ///
    /// Scheme: 5y train + 1y test, 1y step.
    /// Purge gap of (prediction_horizon - 1) days is inserted between train
    /// and test to avoid label leakage.
    std::vector<FoldSpec> walk_forward_splits(
        const std::vector<Date>& dates,
        const std::unordered_map<Date, std::vector<int>>& date_index) const;

    /// Generate Purged K-fold Cross-Validation folds.
    /// @param dates       Sorted vector of all trading dates.
    /// @param date_index  Map from Date to row-index in the feature matrix.
    /// @return K FoldSpec structs.
    ///
    /// K = 5, purge_gap = prediction_horizon - 1, embargo = max(5d, 1% of train).
    /// Purge removes observations within purge_gap days of the test boundary.
    /// Embargo excludes the first embargo_days of data after each test fold
    /// from all training folds.
    std::vector<FoldSpec> purged_kfold_splits(
        const std::vector<Date>& dates,
        const std::unordered_map<Date, std::vector<int>>& date_index) const;

    /// Simple time-series split (single train/test cut).
    SplitIndices time_series_split(
        int n_samples,
        double train_ratio = 0.8) const;

#ifdef HAVE_LIGHTGBM
    // ----- Training pipeline -----------------------------------------------

    /// Full pipeline: load features -> split -> train -> evaluate -> save best.
    /// @param features      N x K feature matrix.
    /// @param labels        N-vector of labels.
    /// @param dates         N-vector of dates (one per sample, for splitting).
    /// @param params        LightGBM hyper-parameters.
    /// @param use_kfold     If true, use purged K-fold CV; otherwise walk-forward.
    /// @return Pipeline result with per-fold metrics and path to best model.
    TrainingPipelineResult run_pipeline(
        const Eigen::MatrixXd& features,
        const Eigen::VectorXd& labels,
        const std::vector<Date>& dates,
        const LGBMParams& params,
        bool use_kfold = false);

    /// Train and evaluate on a single fold.
    FoldResult train_fold(
        const Eigen::MatrixXd& features,
        const Eigen::VectorXd& labels,
        const FoldSpec& fold,
        const LGBMParams& params);
#endif // HAVE_LIGHTGBM

    // ----- Utilities -------------------------------------------------------

    /// Extract sub-matrix and sub-vector by row indices.
    static Eigen::MatrixXd slice_rows(
        const Eigen::MatrixXd& mat,
        const std::vector<int>& indices);

    static Eigen::VectorXd slice_rows(
        const Eigen::VectorXd& vec,
        const std::vector<int>& indices);

    /// Build date_index map from a vector of per-sample dates.
    static std::unordered_map<Date, std::vector<int>> build_date_index(
        const std::vector<Date>& dates);

    const Config& config() const { return config_; }

private:
    Config config_;

#ifdef HAVE_LIGHTGBM
    /// Select the best fold (highest test rank IC) and save the model.
    int select_and_save_best(
        const std::vector<FoldResult>& fold_results,
        const Eigen::MatrixXd& features,
        const Eigen::VectorXd& labels,
        const std::vector<FoldSpec>& folds,
        const LGBMParams& params);
#endif // HAVE_LIGHTGBM
};

} // namespace trade
