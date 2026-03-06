#ifdef HAVE_LIGHTGBM
#include "trade/ml/lgbm_model.h"
#include <LightGBM/c_api.h>
#include <spdlog/spdlog.h>
#include <fmt/format.h>
#include <chrono>

namespace trade {

std::string LGBMParams::to_param_string() const {
    return fmt::format(
        "objective={} metric={} num_leaves={} max_depth={} "
        "learning_rate={} feature_fraction={} bagging_fraction={} "
        "bagging_freq={} lambda_l1={} lambda_l2={} min_data_in_leaf={} "
        "num_threads={} verbose={} seed={}",
        objective, metric, num_leaves, max_depth,
        learning_rate, feature_fraction, bagging_fraction,
        bagging_freq, lambda_l1, lambda_l2, min_data_in_leaf,
        num_threads, verbose, seed);
}

LGBMParams LGBMParams::from_map(
    const std::unordered_map<std::string, std::string>& m) {
    LGBMParams p;
    auto get = [&](const std::string& key, auto& val) {
        auto it = m.find(key);
        if (it != m.end()) {
            std::istringstream iss(it->second);
            iss >> val;
        }
    };
    get("objective", p.objective);
    get("metric", p.metric);
    get("num_leaves", p.num_leaves);
    get("max_depth", p.max_depth);
    get("learning_rate", p.learning_rate);
    get("n_estimators", p.n_estimators);
    get("feature_fraction", p.feature_fraction);
    get("bagging_fraction", p.bagging_fraction);
    return p;
}

LGBMModel::LGBMModel() = default;

LGBMModel::~LGBMModel() {
    if (booster_) {
        LGBM_BoosterFree(booster_);
        booster_ = nullptr;
    }
}

LGBMModel::LGBMModel(LGBMModel&& other) noexcept
    : booster_(other.booster_), num_features_(other.num_features_) {
    other.booster_ = nullptr;
    other.num_features_ = 0;
}

LGBMModel& LGBMModel::operator=(LGBMModel&& other) noexcept {
    if (this != &other) {
        if (booster_) LGBM_BoosterFree(booster_);
        booster_ = other.booster_;
        num_features_ = other.num_features_;
        other.booster_ = nullptr;
        other.num_features_ = 0;
    }
    return *this;
}

void LGBMModel::check_lgbm(int retcode, const std::string& context) {
    if (retcode != 0) {
        const char* err = LGBM_GetLastError();
        throw std::runtime_error(
            fmt::format("LightGBM error in {}: {}", context, err ? err : "unknown"));
    }
}

DatasetHandle LGBMModel::create_dataset(
    const Eigen::MatrixXd& features,
    const Eigen::VectorXd& labels,
    DatasetHandle reference) const {

    int n_rows = static_cast<int>(features.rows());
    int n_cols = static_cast<int>(features.cols());

    // LightGBM expects row-major float64
    // Eigen default is column-major, so we transpose
    Eigen::Matrix<double, Eigen::Dynamic, Eigen::Dynamic, Eigen::RowMajor> row_major = features;

    DatasetHandle dataset = nullptr;
    check_lgbm(LGBM_DatasetCreateFromMat(
        row_major.data(), C_API_DTYPE_FLOAT64,
        n_rows, n_cols, 1,
        "max_bin=255", reference, &dataset), "DatasetCreateFromMat");

    // Set labels
    check_lgbm(LGBM_DatasetSetField(
        dataset, "label", labels.data(), n_rows, C_API_DTYPE_FLOAT64), "SetField:label");

    return dataset;
}

void LGBMModel::free_dataset(DatasetHandle dataset) {
    if (dataset) LGBM_DatasetFree(dataset);
}

LGBMTrainResult LGBMModel::train(
    const Eigen::MatrixXd& features,
    const Eigen::VectorXd& labels,
    const LGBMParams& params,
    const Eigen::MatrixXd& valid_features,
    const Eigen::VectorXd& valid_labels) {

    auto start = std::chrono::high_resolution_clock::now();

    num_features_ = static_cast<int>(features.cols());
    auto train_data = create_dataset(features, labels);

    DatasetHandle valid_data = nullptr;
    bool has_valid = valid_features.rows() > 0;
    if (has_valid) {
        valid_data = create_dataset(valid_features, valid_labels, train_data);
    }

    // Create booster
    if (booster_) { LGBM_BoosterFree(booster_); booster_ = nullptr; }

    std::string param_str = params.to_param_string();
    check_lgbm(LGBM_BoosterCreate(train_data, param_str.c_str(), &booster_),
               "BoosterCreate");

    if (has_valid) {
        check_lgbm(LGBM_BoosterAddValidData(booster_, valid_data), "AddValidData");
    }

    // Training loop
    LGBMTrainResult result;
    result.n_features = num_features_;
    result.n_train_samples = static_cast<int>(features.rows());
    result.n_valid_samples = has_valid ? static_cast<int>(valid_features.rows()) : 0;
    result.metric_name = params.metric;

    double best_score = 1e18;
    int best_iter = 0;
    int no_improve = 0;

    for (int iter = 0; iter < params.n_estimators; ++iter) {
        int is_finished = 0;
        check_lgbm(LGBM_BoosterUpdateOneIter(booster_, &is_finished), "UpdateOneIter");
        if (is_finished) break;

        if (has_valid) {
            int out_len = 0;
            double eval_result = 0;
            check_lgbm(LGBM_BoosterGetEval(booster_, 1, &out_len, &eval_result), "GetEval");

            if (eval_result < best_score) {
                best_score = eval_result;
                best_iter = iter;
                no_improve = 0;
            } else {
                ++no_improve;
            }

            if (params.early_stopping_rounds > 0 &&
                no_improve >= params.early_stopping_rounds) {
                spdlog::debug("Early stopping at iteration {}", iter);
                break;
            }
        }
    }

    result.best_iteration = best_iter;
    result.best_score = best_score;

    auto end = std::chrono::high_resolution_clock::now();
    result.train_time_seconds =
        std::chrono::duration<double>(end - start).count();

    free_dataset(train_data);
    if (valid_data) free_dataset(valid_data);

    spdlog::info("LightGBM trained: {} iters, best={:.6f} at iter {}",
                 params.n_estimators, best_score, best_iter);
    return result;
}

Eigen::VectorXd LGBMModel::predict(const Eigen::MatrixXd& features) const {
    if (!booster_) throw std::runtime_error("Model not trained");

    int n_rows = static_cast<int>(features.rows());
    int n_cols = static_cast<int>(features.cols());

    Eigen::Matrix<double, Eigen::Dynamic, Eigen::Dynamic, Eigen::RowMajor> row_major = features;

    int64_t out_len = 0;
    std::vector<double> out(n_rows);

    check_lgbm(LGBM_BoosterPredictForMat(
        booster_, row_major.data(), C_API_DTYPE_FLOAT64,
        n_rows, n_cols, 1,
        C_API_PREDICT_NORMAL, 0, -1, "",
        &out_len, out.data()), "PredictForMat");

    return Eigen::Map<Eigen::VectorXd>(out.data(), n_rows);
}

double LGBMModel::predict_one(const Eigen::VectorXd& feature_row) const {
    Eigen::MatrixXd mat(1, feature_row.size());
    mat.row(0) = feature_row.transpose();
    return predict(mat)(0);
}

Eigen::VectorXd LGBMModel::feature_importance(int importance_type) const {
    if (!booster_) return {};

    int n_feat = 0;
    LGBM_BoosterGetNumFeature(booster_, &n_feat);

    std::vector<double> importance(n_feat);
    check_lgbm(LGBM_BoosterFeatureImportance(
        booster_, 0, importance_type, importance.data()), "FeatureImportance");

    return Eigen::Map<Eigen::VectorXd>(importance.data(), n_feat);
}

std::vector<std::pair<std::string, double>> LGBMModel::feature_importance_named(
    const std::vector<std::string>& feature_names,
    int importance_type) const {

    auto imp = feature_importance(importance_type);
    std::vector<std::pair<std::string, double>> result;
    for (int i = 0; i < imp.size() && i < static_cast<int>(feature_names.size()); ++i) {
        result.emplace_back(feature_names[i], imp(i));
    }
    std::sort(result.begin(), result.end(),
              [](const auto& a, const auto& b) { return a.second > b.second; });
    return result;
}

Eigen::MatrixXd LGBMModel::shap_values(const Eigen::MatrixXd& features) const {
    if (!booster_) throw std::runtime_error("Model not trained");

    int n_rows = static_cast<int>(features.rows());
    int n_cols = static_cast<int>(features.cols());

    Eigen::Matrix<double, Eigen::Dynamic, Eigen::Dynamic, Eigen::RowMajor> row_major = features;

    int64_t out_len = 0;
    int out_cols = n_cols + 1; // features + bias
    std::vector<double> out(n_rows * out_cols);

    check_lgbm(LGBM_BoosterPredictForMat(
        booster_, row_major.data(), C_API_DTYPE_FLOAT64,
        n_rows, n_cols, 1,
        C_API_PREDICT_CONTRIB, 0, -1, "",
        &out_len, out.data()), "PredictSHAP");

    Eigen::MatrixXd shap(n_rows, out_cols);
    for (int i = 0; i < n_rows; ++i) {
        for (int j = 0; j < out_cols; ++j) {
            shap(i, j) = out[i * out_cols + j];
        }
    }
    return shap;
}

void LGBMModel::save(const std::string& path) const {
    if (!booster_) throw std::runtime_error("No model to save");
    check_lgbm(LGBM_BoosterSaveModel(booster_, 0, -1, 0, path.c_str()),
               "SaveModel");
    spdlog::info("Model saved to {}", path);
}

void LGBMModel::load(const std::string& path) {
    if (booster_) { LGBM_BoosterFree(booster_); booster_ = nullptr; }

    int n_iter = 0;
    check_lgbm(LGBM_BoosterCreateFromModelfile(path.c_str(), &n_iter, &booster_),
               "CreateFromModelfile");

    LGBM_BoosterGetNumFeature(booster_, &num_features_);
    spdlog::info("Model loaded from {} ({} iters, {} features)",
                 path, n_iter, num_features_);
}

std::string LGBMModel::to_string() const {
    if (!booster_) return "";
    int64_t buf_len = 0;
    int64_t out_len = 0;
    // First call: query required buffer size (pass nullptr for out_str)
    LGBM_BoosterSaveModelToString(booster_, 0, -1, 0, buf_len, &out_len, nullptr);
    std::string buf(static_cast<size_t>(out_len), '\0');
    // Second call: fill the buffer
    LGBM_BoosterSaveModelToString(booster_, 0, -1, 0, out_len, &out_len, buf.data());
    return buf;
}

void LGBMModel::from_string(const std::string& model_str) {
    if (booster_) { LGBM_BoosterFree(booster_); booster_ = nullptr; }
    int n_iter = 0;
    check_lgbm(LGBM_BoosterLoadModelFromString(model_str.c_str(), &n_iter, &booster_),
               "LoadModelFromString");
    LGBM_BoosterGetNumFeature(booster_, &num_features_);
}

int LGBMModel::num_iterations() const {
    if (!booster_) return 0;
    int n = 0;
    LGBM_BoosterGetCurrentIteration(booster_, &n);
    return n;
}

int LGBMModel::num_classes() const {
    if (!booster_) return 1;
    int n = 0;
    LGBM_BoosterGetNumClasses(booster_, &n);
    return n;
}

} // namespace trade

#endif // HAVE_LIGHTGBM
