#include "trade/ml/model_trainer.h"

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <numeric>
#include <set>
#include <stdexcept>

namespace trade {

void ModelTrainer::Config::resolve_defaults(int train_size) {
    if (purge_gap < 0) purge_gap = prediction_horizon - 1;
    if (embargo_days < 0)
        embargo_days = std::max(5, static_cast<int>(0.01 * train_size));
}

ModelTrainer::ModelTrainer(Config config) : config_(std::move(config)) {}

// ---------------------------------------------------------------------------
// Helper: collect row indices from date_index for all dates in [start, end)
// ---------------------------------------------------------------------------
static std::vector<int> collect_indices(
    const std::vector<Date>& dates,
    const std::unordered_map<Date, std::vector<int>>& date_index,
    Date start, Date end) {
    std::vector<int> indices;
    for (const auto& d : dates) {
        if (d >= start && d < end) {
            auto it = date_index.find(d);
            if (it != date_index.end()) {
                indices.insert(indices.end(), it->second.begin(), it->second.end());
            }
        }
    }
    // Remove duplicates (dates may repeat in the sorted vector, but
    // date_index gives us the canonical indices per unique date).
    std::sort(indices.begin(), indices.end());
    indices.erase(std::unique(indices.begin(), indices.end()), indices.end());
    return indices;
}

// ---------------------------------------------------------------------------
// Helper: get sorted unique dates
// ---------------------------------------------------------------------------
static std::vector<Date> unique_sorted_dates(const std::vector<Date>& dates) {
    std::set<Date> s(dates.begin(), dates.end());
    return {s.begin(), s.end()};
}

// ---------------------------------------------------------------------------
// walk_forward_splits
// ---------------------------------------------------------------------------
std::vector<FoldSpec> ModelTrainer::walk_forward_splits(
    const std::vector<Date>& dates,
    const std::unordered_map<Date, std::vector<int>>& date_index) const {
    if (dates.empty()) return {};

    std::vector<Date> unique_dates = unique_sorted_dates(dates);
    Date first_date = unique_dates.front();
    Date last_date = unique_dates.back();

    // Purge gap in calendar days
    auto purge = std::chrono::days(config_.purge_gap >= 0
        ? config_.purge_gap
        : std::max(0, config_.prediction_horizon - 1));

    auto train_dur = std::chrono::days(365 * config_.train_years);
    auto test_dur = std::chrono::days(365 * config_.test_years);
    auto step_dur = std::chrono::days(365 * config_.step_years);

    std::vector<FoldSpec> folds;
    int fold_id = 0;

    Date train_start = first_date;
    while (true) {
        Date train_end = train_start + train_dur;           // exclusive
        Date test_start = train_end + purge;                // skip purge gap
        Date test_end = test_start + test_dur;              // exclusive

        // Stop if test window extends beyond available data
        if (test_start > last_date) break;

        FoldSpec fold;
        fold.fold_id = fold_id++;
        fold.train_start = train_start;
        fold.train_end = train_end;
        fold.valid_start = test_start;
        fold.valid_end = test_end;
        fold.embargo_end = test_end; // no extra embargo in walk-forward

        // Collect row indices
        fold.indices.train = collect_indices(dates, date_index, train_start, train_end);
        fold.indices.test = collect_indices(dates, date_index, test_start, test_end);
        // valid is left empty for walk-forward (train_fold will carve it out of train)

        if (!fold.indices.train.empty() && !fold.indices.test.empty()) {
            folds.push_back(std::move(fold));
        }

        train_start = train_start + step_dur;
    }

    return folds;
}

// ---------------------------------------------------------------------------
// purged_kfold_splits
// ---------------------------------------------------------------------------
std::vector<FoldSpec> ModelTrainer::purged_kfold_splits(
    const std::vector<Date>& dates,
    const std::unordered_map<Date, std::vector<int>>& date_index) const {
    if (dates.empty()) return {};

    std::vector<Date> unique_dates = unique_sorted_dates(dates);
    int n_dates = static_cast<int>(unique_dates.size());
    int k = config_.n_folds;
    if (k <= 1) {
        throw std::invalid_argument("n_folds must be >= 2");
    }

    auto purge_gap_days = std::chrono::days(config_.purge_gap >= 0
        ? config_.purge_gap
        : std::max(0, config_.prediction_horizon - 1));
    auto embargo = std::chrono::days(config_.embargo_days >= 0
        ? config_.embargo_days
        : std::max(5, static_cast<int>(0.01 * n_dates)));

    // Split unique dates into K roughly equal groups
    std::vector<std::vector<Date>> groups(k);
    for (int i = 0; i < n_dates; ++i) {
        int group_idx = static_cast<int>(static_cast<long long>(i) * k / n_dates);
        groups[group_idx].push_back(unique_dates[i]);
    }

    std::vector<FoldSpec> folds;

    for (int fold_k = 0; fold_k < k; ++fold_k) {
        const auto& test_dates_group = groups[fold_k];
        if (test_dates_group.empty()) continue;

        Date test_start = test_dates_group.front();
        Date test_end_inclusive = test_dates_group.back();
        // For boundary computation, test_end is one day past the last test date
        Date test_end = test_end_inclusive + std::chrono::days(1);

        // Purge boundary: dates within purge_gap_days of test boundaries
        // are excluded from train
        Date purge_before_start = test_start - purge_gap_days;
        Date purge_after_end = test_end + purge_gap_days;

        // Embargo: exclude first embargo_days after test fold from train
        Date embargo_end = test_end + embargo;

        FoldSpec fold;
        fold.fold_id = fold_k;
        fold.train_start = unique_dates.front();
        fold.train_end = test_start;  // approximate; actual train is everything outside test+purge+embargo
        fold.valid_start = test_start;
        fold.valid_end = test_end;
        fold.embargo_end = embargo_end;

        // Test indices: all rows with dates in the test group
        std::set<Date> test_date_set(test_dates_group.begin(), test_dates_group.end());
        for (const auto& d : test_dates_group) {
            auto it = date_index.find(d);
            if (it != date_index.end()) {
                fold.indices.test.insert(fold.indices.test.end(),
                    it->second.begin(), it->second.end());
            }
        }
        std::sort(fold.indices.test.begin(), fold.indices.test.end());

        // Train indices: all dates NOT in test, NOT in purge zone, NOT in embargo zone
        for (const auto& d : unique_dates) {
            // Skip if date is in the test set
            if (test_date_set.count(d)) continue;

            // Skip if date is within purge gap of test boundaries
            if (d >= purge_before_start && d < test_start) continue;
            if (d >= test_end && d < purge_after_end) continue;

            // Skip if date is in embargo period (first embargo_days after test)
            if (d >= test_end && d < embargo_end) continue;

            auto it = date_index.find(d);
            if (it != date_index.end()) {
                fold.indices.train.insert(fold.indices.train.end(),
                    it->second.begin(), it->second.end());
            }
        }
        std::sort(fold.indices.train.begin(), fold.indices.train.end());

        if (!fold.indices.train.empty() && !fold.indices.test.empty()) {
            folds.push_back(std::move(fold));
        }
    }

    return folds;
}

// ---------------------------------------------------------------------------
// time_series_split
// ---------------------------------------------------------------------------
SplitIndices ModelTrainer::time_series_split(
    int n_samples, double train_ratio) const {
    SplitIndices split;
    int train_end = static_cast<int>(n_samples * train_ratio);
    for (int i = 0; i < train_end; ++i) split.train.push_back(i);
    for (int i = train_end; i < n_samples; ++i) split.test.push_back(i);
    return split;
}

#ifdef HAVE_LIGHTGBM

// ---------------------------------------------------------------------------
// Helper: Pearson correlation coefficient
// ---------------------------------------------------------------------------
static double pearson_correlation(const Eigen::VectorXd& x, const Eigen::VectorXd& y) {
    if (x.size() != y.size() || x.size() < 2) return 0.0;

    double n = static_cast<double>(x.size());
    double mean_x = x.mean();
    double mean_y = y.mean();

    double cov = 0.0;
    double var_x = 0.0;
    double var_y = 0.0;

    for (Eigen::Index i = 0; i < x.size(); ++i) {
        double dx = x(i) - mean_x;
        double dy = y(i) - mean_y;
        cov += dx * dy;
        var_x += dx * dx;
        var_y += dy * dy;
    }

    double denom = std::sqrt(var_x * var_y);
    if (denom < 1e-15) return 0.0;
    return cov / denom;
}

// ---------------------------------------------------------------------------
// Helper: rank transform (average ranks for ties)
// ---------------------------------------------------------------------------
static Eigen::VectorXd rank_transform(const Eigen::VectorXd& v) {
    int n = static_cast<int>(v.size());
    std::vector<int> order(n);
    std::iota(order.begin(), order.end(), 0);
    std::sort(order.begin(), order.end(), [&](int a, int b) {
        return v(a) < v(b);
    });

    Eigen::VectorXd ranks(n);
    int i = 0;
    while (i < n) {
        int j = i;
        // Find all elements with the same value (ties)
        while (j < n - 1 && v(order[j + 1]) == v(order[j])) {
            ++j;
        }
        // Average rank for ties: positions are 1-based
        double avg_rank = 0.5 * (i + 1 + j + 1);
        for (int k = i; k <= j; ++k) {
            ranks(order[k]) = avg_rank;
        }
        i = j + 1;
    }
    return ranks;
}

// ---------------------------------------------------------------------------
// Helper: Spearman rank correlation
// ---------------------------------------------------------------------------
static double spearman_correlation(const Eigen::VectorXd& x, const Eigen::VectorXd& y) {
    if (x.size() != y.size() || x.size() < 2) return 0.0;
    Eigen::VectorXd rx = rank_transform(x);
    Eigen::VectorXd ry = rank_transform(y);
    return pearson_correlation(rx, ry);
}

// ---------------------------------------------------------------------------
// run_pipeline
// ---------------------------------------------------------------------------
TrainingPipelineResult ModelTrainer::run_pipeline(
    const Eigen::MatrixXd& features,
    const Eigen::VectorXd& labels,
    const std::vector<Date>& dates,
    const LGBMParams& params,
    bool use_kfold) {

    // Build date_index from dates
    auto date_index = build_date_index(dates);

    // Generate folds
    std::vector<FoldSpec> folds;
    if (use_kfold) {
        folds = purged_kfold_splits(dates, date_index);
    } else {
        folds = walk_forward_splits(dates, date_index);
    }

    if (folds.empty()) {
        throw std::runtime_error("ModelTrainer::run_pipeline: no valid folds generated");
    }

    // Resolve default config values
    config_.resolve_defaults(static_cast<int>(dates.size()));

    // Train each fold
    std::vector<FoldResult> fold_results;
    fold_results.reserve(folds.size());
    for (const auto& fold : folds) {
        fold_results.push_back(train_fold(features, labels, fold, params));
    }

    // Compute aggregate metrics
    double sum_ic = 0.0;
    double sum_rank_ic = 0.0;
    double sum_ic_sq = 0.0;
    int n_folds = static_cast<int>(fold_results.size());

    for (const auto& fr : fold_results) {
        sum_ic += fr.test_ic;
        sum_rank_ic += fr.test_rank_ic;
        sum_ic_sq += fr.test_ic * fr.test_ic;
    }

    double mean_ic = sum_ic / n_folds;
    double mean_rank_ic = sum_rank_ic / n_folds;
    double std_ic = 0.0;
    if (n_folds > 1) {
        double variance = (sum_ic_sq / n_folds) - (mean_ic * mean_ic);
        std_ic = std::sqrt(std::max(0.0, variance));
    }

    // Select best fold and save model
    int best_fold_id = select_and_save_best(fold_results, features, labels, folds, params);

    // Build result
    TrainingPipelineResult result;
    result.fold_results = std::move(fold_results);
    result.mean_test_ic = mean_ic;
    result.mean_test_rank_ic = mean_rank_ic;
    result.std_test_ic = std_ic;
    result.best_fold_id = best_fold_id;
    result.best_params = params;

    // Construct best model path
    std::filesystem::path out_dir(config_.model_output_dir);
    std::string model_filename = config_.model_name_prefix + "_best.model";
    result.best_model_path = (out_dir / model_filename).string();

    return result;
}

// ---------------------------------------------------------------------------
// train_fold
// ---------------------------------------------------------------------------
FoldResult ModelTrainer::train_fold(
    const Eigen::MatrixXd& features,
    const Eigen::VectorXd& labels,
    const FoldSpec& fold,
    const LGBMParams& params) {

    FoldResult result;
    result.fold_id = fold.fold_id;

    // Slice features and labels for train and test
    Eigen::MatrixXd train_features = slice_rows(features, fold.indices.train);
    Eigen::VectorXd train_labels = slice_rows(labels, fold.indices.train);
    Eigen::MatrixXd test_features = slice_rows(features, fold.indices.test);
    Eigen::VectorXd test_labels = slice_rows(labels, fold.indices.test);

    // Determine validation set
    Eigen::MatrixXd valid_features;
    Eigen::VectorXd valid_labels;

    if (!fold.indices.valid.empty()) {
        // Use the provided validation indices
        valid_features = slice_rows(features, fold.indices.valid);
        valid_labels = slice_rows(labels, fold.indices.valid);
    } else {
        // Use the last 20% of train as validation
        int n_train = static_cast<int>(fold.indices.train.size());
        int valid_start = static_cast<int>(n_train * 0.8);
        if (valid_start < n_train) {
            std::vector<int> valid_indices(
                fold.indices.train.begin() + valid_start,
                fold.indices.train.end());
            std::vector<int> actual_train_indices(
                fold.indices.train.begin(),
                fold.indices.train.begin() + valid_start);

            valid_features = slice_rows(features, valid_indices);
            valid_labels = slice_rows(labels, valid_indices);

            // Shrink train to the first 80%
            train_features = slice_rows(features, actual_train_indices);
            train_labels = slice_rows(labels, actual_train_indices);
        }
    }

    // Create model and train
    LGBMModel model;
    result.train_result = model.train(
        train_features, train_labels, params,
        valid_features, valid_labels);

    // Predict on test set
    result.predictions = model.predict(test_features);
    result.actuals = test_labels;

    // Compute test IC (Pearson correlation)
    result.test_ic = pearson_correlation(result.predictions, result.actuals);

    // Compute test rank IC (Spearman correlation)
    result.test_rank_ic = spearman_correlation(result.predictions, result.actuals);

    // Compute MSE
    Eigen::VectorXd residuals = result.predictions - result.actuals;
    result.test_mse = residuals.squaredNorm() / static_cast<double>(residuals.size());

    // Compute MAE
    result.test_mae = residuals.array().abs().mean();

    return result;
}

// ---------------------------------------------------------------------------
// select_and_save_best
// ---------------------------------------------------------------------------
int ModelTrainer::select_and_save_best(
    const std::vector<FoldResult>& fold_results,
    const Eigen::MatrixXd& features,
    const Eigen::VectorXd& labels,
    const std::vector<FoldSpec>& folds,
    const LGBMParams& params) {

    if (fold_results.empty()) return -1;

    // Select fold with highest test_rank_ic
    int best_idx = 0;
    double best_rank_ic = fold_results[0].test_rank_ic;
    for (int i = 1; i < static_cast<int>(fold_results.size()); ++i) {
        if (fold_results[i].test_rank_ic > best_rank_ic) {
            best_rank_ic = fold_results[i].test_rank_ic;
            best_idx = i;
        }
    }

    int best_fold_id = fold_results[best_idx].fold_id;

    // Find the corresponding FoldSpec
    const FoldSpec* best_fold = nullptr;
    for (const auto& f : folds) {
        if (f.fold_id == best_fold_id) {
            best_fold = &f;
            break;
        }
    }
    if (!best_fold) return best_fold_id;

    // Retrain on full data from that fold (train + valid combined)
    std::vector<int> full_train_indices = best_fold->indices.train;
    if (!best_fold->indices.valid.empty()) {
        full_train_indices.insert(full_train_indices.end(),
            best_fold->indices.valid.begin(),
            best_fold->indices.valid.end());
    }
    std::sort(full_train_indices.begin(), full_train_indices.end());

    Eigen::MatrixXd full_train_features = slice_rows(features, full_train_indices);
    Eigen::VectorXd full_train_labels = slice_rows(labels, full_train_indices);

    // Train the final model (no validation set for final retraining;
    // use n_estimators from best iteration if available)
    LGBMParams final_params = params;
    if (fold_results[best_idx].train_result.best_iteration > 0) {
        final_params.n_estimators = fold_results[best_idx].train_result.best_iteration;
        final_params.early_stopping_rounds = 0; // no early stopping without valid set
    }

    LGBMModel model;
    model.train(full_train_features, full_train_labels, final_params);

    // Ensure output directory exists
    std::filesystem::path out_dir(config_.model_output_dir);
    std::filesystem::create_directories(out_dir);

    // Save model
    std::string model_filename = config_.model_name_prefix + "_best.model";
    std::string model_path = (out_dir / model_filename).string();
    model.save(model_path);

    return best_fold_id;
}

#endif // HAVE_LIGHTGBM

// ---------------------------------------------------------------------------
// slice_rows (MatrixXd)
// ---------------------------------------------------------------------------
Eigen::MatrixXd ModelTrainer::slice_rows(
    const Eigen::MatrixXd& mat,
    const std::vector<int>& indices) {
    Eigen::MatrixXd result(indices.size(), mat.cols());
    for (size_t i = 0; i < indices.size(); ++i) {
        result.row(static_cast<int>(i)) = mat.row(indices[i]);
    }
    return result;
}

// ---------------------------------------------------------------------------
// slice_rows (VectorXd)
// ---------------------------------------------------------------------------
Eigen::VectorXd ModelTrainer::slice_rows(
    const Eigen::VectorXd& vec,
    const std::vector<int>& indices) {
    Eigen::VectorXd result(indices.size());
    for (size_t i = 0; i < indices.size(); ++i) {
        result(static_cast<int>(i)) = vec(indices[i]);
    }
    return result;
}

// ---------------------------------------------------------------------------
// build_date_index
// ---------------------------------------------------------------------------
std::unordered_map<Date, std::vector<int>> ModelTrainer::build_date_index(
    const std::vector<Date>& dates) {
    std::unordered_map<Date, std::vector<int>> index;
    for (int i = 0; i < static_cast<int>(dates.size()); ++i) {
        index[dates[i]].push_back(i);
    }
    return index;
}

} // namespace trade
