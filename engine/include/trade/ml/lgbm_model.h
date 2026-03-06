#pragma once

#include "trade/common/types.h"
#include <Eigen/Dense>
#include <string>
#include <vector>
#include <unordered_map>
#include <memory>
#include <stdexcept>

#ifdef HAVE_LIGHTGBM

// Forward-declare LightGBM C API opaque handles
using DatasetHandle = void*;
using BoosterHandle = void*;

namespace trade {

// ---------------------------------------------------------------------------
// LightGBM hyper-parameter set (string key-value, passed to LGBM C API)
// ---------------------------------------------------------------------------
struct LGBMParams {
    std::string objective = "regression";      // "regression", "binary", "lambdarank"
    std::string metric = "mse";                // "mse", "mae", "auc", "ndcg"
    int num_leaves = 63;
    int max_depth = -1;                        // -1 = unlimited
    double learning_rate = 0.05;
    int n_estimators = 500;
    double feature_fraction = 0.8;
    double bagging_fraction = 0.8;
    int bagging_freq = 5;
    double lambda_l1 = 0.0;
    double lambda_l2 = 1.0;
    int min_data_in_leaf = 50;
    int num_threads = 0;                       // 0 = auto
    int verbose = -1;                          // -1 = silent
    int early_stopping_rounds = 50;
    int seed = 42;

    /// Serialise to the "key1=value1 key2=value2 ..." format expected by
    /// LGBM_BoosterCreate.
    std::string to_param_string() const;

    /// Build from a generic key-value map (e.g., loaded from YAML config).
    static LGBMParams from_map(const std::unordered_map<std::string, std::string>& m);
};

// ---------------------------------------------------------------------------
// Training result metadata
// ---------------------------------------------------------------------------
struct LGBMTrainResult {
    int best_iteration = 0;
    double best_score = 0.0;            // best validation metric
    std::string metric_name;
    int n_features = 0;
    int n_train_samples = 0;
    int n_valid_samples = 0;
    double train_time_seconds = 0.0;
};

// ---------------------------------------------------------------------------
// LGBMModel: thin C++ wrapper around the LightGBM C API
// ---------------------------------------------------------------------------
class LGBMModel {
public:
    LGBMModel();
    ~LGBMModel();

    // Non-copyable, movable
    LGBMModel(const LGBMModel&) = delete;
    LGBMModel& operator=(const LGBMModel&) = delete;
    LGBMModel(LGBMModel&& other) noexcept;
    LGBMModel& operator=(LGBMModel&& other) noexcept;

    // ----- Training -------------------------------------------------------

    /// Train a model from dense feature matrix and label vector.
    /// @param features      N x K column-major matrix (N samples, K features).
    /// @param labels        N-vector of target values.
    /// @param params        Hyper-parameters.
    /// @param valid_features  Optional validation feature matrix.
    /// @param valid_labels    Optional validation labels.
    /// @return Training result metadata.
    ///
    /// Internally calls:
    ///   LGBM_DatasetCreateFromMat  (train + valid)
    ///   LGBM_BoosterCreate
    ///   LGBM_BoosterUpdateOneIter  (loop)
    ///   LGBM_BoosterGetEval        (early stopping check)
    LGBMTrainResult train(
        const Eigen::MatrixXd& features,
        const Eigen::VectorXd& labels,
        const LGBMParams& params,
        const Eigen::MatrixXd& valid_features = Eigen::MatrixXd(),
        const Eigen::VectorXd& valid_labels = Eigen::VectorXd());

    // ----- Prediction -----------------------------------------------------

    /// Predict on a dense feature matrix.
    /// @param features  M x K matrix (M samples, K features).
    /// @return M-vector of predictions.
    ///
    /// Internally calls LGBM_BoosterPredictForMat.
    Eigen::VectorXd predict(const Eigen::MatrixXd& features) const;

    /// Predict on a single sample (row vector).
    double predict_one(const Eigen::VectorXd& feature_row) const;

    // ----- Feature importance ---------------------------------------------

    /// Feature importance (gain-based or split-based).
    /// @param importance_type  0 = split, 1 = gain.
    /// @return K-vector of importance scores.
    ///
    /// Internally calls LGBM_BoosterFeatureImportance.
    Eigen::VectorXd feature_importance(int importance_type = 1) const;

    /// Feature importance with names.
    std::vector<std::pair<std::string, double>> feature_importance_named(
        const std::vector<std::string>& feature_names,
        int importance_type = 1) const;

    // ----- SHAP values ----------------------------------------------------

    /// Compute SHAP values for a set of samples.
    /// @param features  M x K matrix.
    /// @return M x (K+1) matrix; last column is the base value (expected output).
    ///
    /// Internally calls LGBM_BoosterPredictForMat with predict_type = SHAP.
    Eigen::MatrixXd shap_values(const Eigen::MatrixXd& features) const;

    // ----- Persistence ----------------------------------------------------

    /// Save model to file.
    /// Internally calls LGBM_BoosterSaveModel.
    void save(const std::string& path) const;

    /// Load model from file.
    /// Internally calls LGBM_BoosterCreateFromModelfile.
    void load(const std::string& path);

    /// Serialise model to string (for embedding in configs).
    std::string to_string() const;

    /// Load from model string.
    void from_string(const std::string& model_str);

    // ----- Accessors -------------------------------------------------------

    bool is_trained() const { return booster_ != nullptr; }
    int num_features() const { return num_features_; }
    int num_iterations() const;
    int num_classes() const;

private:
    BoosterHandle booster_ = nullptr;
    int num_features_ = 0;

    /// Internal helper: create a DatasetHandle from dense matrix + labels.
    DatasetHandle create_dataset(
        const Eigen::MatrixXd& features,
        const Eigen::VectorXd& labels,
        DatasetHandle reference = nullptr) const;

    /// Free a DatasetHandle.
    static void free_dataset(DatasetHandle dataset);

    /// Check LightGBM return code and throw on error.
    static void check_lgbm(int retcode, const std::string& context);
};

} // namespace trade

#endif // HAVE_LIGHTGBM
