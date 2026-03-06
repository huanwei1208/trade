#pragma once

#include "trade/common/types.h"
#include <Eigen/Dense>
#include <string>
#include <vector>
#include <unordered_map>
#include <memory>

// Forward-declare XGBoost C API opaque handles.
using DMatrixHandle = void*;
using BoosterHandle_XGB = void*;  // disambiguate from LightGBM BoosterHandle

namespace trade {

// ---------------------------------------------------------------------------
// XGBoost hyper-parameter set
// ---------------------------------------------------------------------------
struct XGBParams {
    std::string objective = "reg:squarederror";  // "binary:logistic", "rank:pairwise"
    std::string eval_metric = "rmse";            // "mae", "auc", "ndcg"
    int max_depth = 6;
    double learning_rate = 0.05;                 // eta
    int n_estimators = 500;
    double subsample = 0.8;
    double colsample_bytree = 0.8;
    double reg_alpha = 0.0;                      // L1 regularisation
    double reg_lambda = 1.0;                     // L2 regularisation
    int min_child_weight = 5;
    double gamma = 0.0;                          // min split loss
    int nthread = 0;                             // 0 = auto
    int verbosity = 0;                           // 0 = silent
    int early_stopping_rounds = 50;
    int seed = 42;

    /// Serialise to key-value pairs for XGBoost C API (XGBoosterSetParam).
    std::vector<std::pair<std::string, std::string>> to_param_pairs() const;

    /// Build from a generic key-value map.
    static XGBParams from_map(const std::unordered_map<std::string, std::string>& m);
};

// ---------------------------------------------------------------------------
// Training result metadata
// ---------------------------------------------------------------------------
struct XGBTrainResult {
    int best_iteration = 0;
    double best_score = 0.0;
    std::string metric_name;
    int n_features = 0;
    int n_train_samples = 0;
    int n_valid_samples = 0;
    double train_time_seconds = 0.0;
};

// ---------------------------------------------------------------------------
// XGBModel: thin C++ wrapper around the XGBoost C API (Phase 3 placeholder)
//
// The interface mirrors LGBMModel so that ModelTrainer and ModelEvaluator
// can work with either backend through a common pattern.
// ---------------------------------------------------------------------------
class XGBModel {
public:
    XGBModel();
    ~XGBModel();

    // Non-copyable, movable
    XGBModel(const XGBModel&) = delete;
    XGBModel& operator=(const XGBModel&) = delete;
    XGBModel(XGBModel&& other) noexcept;
    XGBModel& operator=(XGBModel&& other) noexcept;

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
    ///   XGDMatrixCreateFromMat  (train + valid)
    ///   XGBoosterCreate
    ///   XGBoosterUpdateOneIter  (loop)
    ///   XGBoosterEvalOneIter    (early stopping check)
    XGBTrainResult train(
        const Eigen::MatrixXd& features,
        const Eigen::VectorXd& labels,
        const XGBParams& params,
        const Eigen::MatrixXd& valid_features = Eigen::MatrixXd(),
        const Eigen::VectorXd& valid_labels = Eigen::VectorXd());

    // ----- Prediction -----------------------------------------------------

    /// Predict on a dense feature matrix.
    /// @param features  M x K matrix (M samples, K features).
    /// @return M-vector of predictions.
    ///
    /// Internally calls XGBoosterPredict.
    Eigen::VectorXd predict(const Eigen::MatrixXd& features) const;

    /// Predict on a single sample.
    double predict_one(const Eigen::VectorXd& feature_row) const;

    // ----- Feature importance ---------------------------------------------

    /// Feature importance (gain, weight, cover, total_gain, total_cover).
    /// @param importance_type  "gain", "weight", "cover", "total_gain", "total_cover".
    /// @return K-vector of importance scores.
    Eigen::VectorXd feature_importance(
        const std::string& importance_type = "gain") const;

    /// Feature importance with names.
    std::vector<std::pair<std::string, double>> feature_importance_named(
        const std::vector<std::string>& feature_names,
        const std::string& importance_type = "gain") const;

    // ----- SHAP values ----------------------------------------------------

    /// Compute SHAP values for a set of samples.
    /// @param features  M x K matrix.
    /// @return M x (K+1) matrix; last column is the base value.
    Eigen::MatrixXd shap_values(const Eigen::MatrixXd& features) const;

    // ----- Persistence ----------------------------------------------------

    /// Save model to file (binary or JSON format).
    void save(const std::string& path) const;

    /// Load model from file.
    void load(const std::string& path);

    /// Serialise model to JSON string.
    std::string to_json() const;

    /// Load from JSON string.
    void from_json(const std::string& json_str);

    // ----- Accessors -------------------------------------------------------

    bool is_trained() const { return booster_ != nullptr; }
    int num_features() const { return num_features_; }
    int num_iterations() const;

private:
    BoosterHandle_XGB booster_ = nullptr;
    int num_features_ = 0;

    /// Create a DMatrixHandle from dense matrix + labels.
    DMatrixHandle create_dmatrix(
        const Eigen::MatrixXd& features,
        const Eigen::VectorXd& labels) const;

    /// Free a DMatrixHandle.
    static void free_dmatrix(DMatrixHandle dm);

    /// Check XGBoost return code and throw on error.
    static void check_xgb(int retcode, const std::string& context);
};

} // namespace trade
