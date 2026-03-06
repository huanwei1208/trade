#include "trade/features/preprocessor.h"
#include <algorithm>
#include <cmath>
#include <numeric>

namespace trade {

Preprocessor::Preprocessor(PreprocessorConfig cfg) : config_(std::move(cfg)) {}

std::unordered_map<Date, std::vector<int>> Preprocessor::build_date_index(
    const std::vector<Date>& dates) {
    std::unordered_map<Date, std::vector<int>> idx;
    for (int i = 0; i < static_cast<int>(dates.size()); ++i) {
        idx[dates[i]].push_back(i);
    }
    return idx;
}

std::unordered_map<Symbol, std::vector<int>> Preprocessor::build_stock_blocks(
    const std::vector<Symbol>& symbols) {
    std::unordered_map<Symbol, std::vector<int>> blocks;
    for (int i = 0; i < static_cast<int>(symbols.size()); ++i) {
        blocks[symbols[i]].push_back(i);
    }
    return blocks;
}

std::pair<double, double> Preprocessor::winsor_bounds(const std::string& name) const {
    if (config_.fundamental_features.count(name)) {
        return {config_.fund_lower_pct, config_.fund_upper_pct};
    }
    return {config_.price_lower_pct, config_.price_upper_pct};
}

void Preprocessor::forward_fill(
    Eigen::MatrixXd& mat,
    const std::unordered_map<Symbol, std::vector<int>>& stock_blocks) {
    int n_cols = static_cast<int>(mat.cols());
    for (const auto& [sym, rows] : stock_blocks) {
        // Rows for this stock should be in time order
        for (int c = 0; c < n_cols; ++c) {
            double last_valid = std::numeric_limits<double>::quiet_NaN();
            for (int r : rows) {
                if (std::isnan(mat(r, c))) {
                    if (!std::isnan(last_valid)) {
                        mat(r, c) = last_valid;
                    }
                } else {
                    last_valid = mat(r, c);
                }
            }
        }
    }
}

Eigen::MatrixXd Preprocessor::make_missing_flags(const Eigen::MatrixXd& mat) {
    Eigen::MatrixXd flags(mat.rows(), mat.cols());
    for (int r = 0; r < mat.rows(); ++r) {
        for (int c = 0; c < mat.cols(); ++c) {
            flags(r, c) = std::isnan(mat(r, c)) ? 1.0 : 0.0;
        }
    }
    return flags;
}

void Preprocessor::winsorize(
    Eigen::MatrixXd& mat,
    int col,
    double lower_pct,
    double upper_pct,
    const std::unordered_map<Date, std::vector<int>>& date_indices) {

    for (const auto& [dt, rows] : date_indices) {
        // Collect valid values
        std::vector<double> vals;
        vals.reserve(rows.size());
        for (int r : rows) {
            if (!std::isnan(mat(r, col))) {
                vals.push_back(mat(r, col));
            }
        }
        if (vals.size() < 3) continue;

        std::sort(vals.begin(), vals.end());
        int n = static_cast<int>(vals.size());
        double lo = vals[std::max(0, static_cast<int>(lower_pct * n))];
        double hi = vals[std::min(n - 1, static_cast<int>(upper_pct * n))];

        for (int r : rows) {
            if (!std::isnan(mat(r, col))) {
                mat(r, col) = std::clamp(mat(r, col), lo, hi);
            }
        }
    }
}

void Preprocessor::neutralize(
    Eigen::MatrixXd& mat,
    int col,
    const std::vector<SWIndustry>& industries,
    const Eigen::VectorXd& log_market_caps,
    const std::unordered_map<Date, std::vector<int>>& date_indices) {

    for (const auto& [dt, rows] : date_indices) {
        // Collect valid indices
        std::vector<int> valid;
        for (int r : rows) {
            if (!std::isnan(mat(r, col)) && !std::isnan(log_market_caps(r))) {
                valid.push_back(r);
            }
        }
        int n = static_cast<int>(valid.size());
        if (n < 10) continue;

        // Find unique industries in this cross-section
        std::unordered_map<int, int> ind_map;
        int ind_count = 0;
        for (int r : valid) {
            int ind = static_cast<int>(industries[r]);
            if (ind_map.find(ind) == ind_map.end()) {
                ind_map[ind] = ind_count++;
            }
        }

        // Build design matrix: [industry_dummies | log_mktcap]
        int k = ind_count + 1; // +1 for log_mktcap
        Eigen::MatrixXd X(n, k);
        Eigen::VectorXd y(n);
        X.setZero();

        for (int i = 0; i < n; ++i) {
            int r = valid[i];
            y(i) = mat(r, col);
            int ind = static_cast<int>(industries[r]);
            X(i, ind_map[ind]) = 1.0;
            X(i, ind_count) = log_market_caps(r);
        }

        // OLS: beta = (X'X)^{-1} X'y, residual = y - X*beta
        Eigen::VectorXd beta = (X.transpose() * X).ldlt().solve(X.transpose() * y);
        Eigen::VectorXd residuals = y - X * beta;

        // Write residuals back
        for (int i = 0; i < n; ++i) {
            mat(valid[i], col) = residuals(i);
        }
    }
}

void Preprocessor::standardize_zscore(
    Eigen::MatrixXd& mat,
    int col,
    const std::unordered_map<Date, std::vector<int>>& date_indices) {

    for (const auto& [dt, rows] : date_indices) {
        double sum = 0;
        int count = 0;
        for (int r : rows) {
            if (!std::isnan(mat(r, col))) {
                sum += mat(r, col);
                ++count;
            }
        }
        if (count < 2) continue;
        double mean = sum / count;

        double sum2 = 0;
        for (int r : rows) {
            if (!std::isnan(mat(r, col))) {
                double d = mat(r, col) - mean;
                sum2 += d * d;
            }
        }
        double std_dev = std::sqrt(sum2 / (count - 1));
        if (std_dev < 1e-15) continue;

        for (int r : rows) {
            if (!std::isnan(mat(r, col))) {
                mat(r, col) = (mat(r, col) - mean) / std_dev;
            }
        }
    }
}

void Preprocessor::standardize_quantile_rank(
    Eigen::MatrixXd& mat,
    int col,
    const std::unordered_map<Date, std::vector<int>>& date_indices) {

    for (const auto& [dt, rows] : date_indices) {
        std::vector<int> valid;
        for (int r : rows) {
            if (!std::isnan(mat(r, col))) valid.push_back(r);
        }
        if (valid.empty()) continue;

        // Sort by value
        std::sort(valid.begin(), valid.end(),
                  [&](int a, int b) { return mat(a, col) < mat(b, col); });

        double denom = static_cast<double>(valid.size()) - 1.0;
        if (denom <= 0) denom = 1.0;
        for (int i = 0; i < static_cast<int>(valid.size()); ++i) {
            mat(valid[i], col) = static_cast<double>(i) / denom;
        }
    }
}

Eigen::MatrixXd Preprocessor::run(
    const Eigen::MatrixXd& raw,
    std::vector<std::string>& feature_names,
    const std::vector<Symbol>& symbols,
    const std::vector<Date>& dates,
    const std::unordered_map<Symbol, Instrument>& instruments) const {

    Eigen::MatrixXd mat = raw;
    int n_cols = static_cast<int>(mat.cols());

    // Build indices
    auto stock_blocks = build_stock_blocks(symbols);
    auto date_idx = build_date_index(dates);

    // 1. Missing value handling
    Eigen::MatrixXd missing_flags;
    if (config_.add_is_missing_flag) {
        missing_flags = make_missing_flags(mat);
    }
    if (config_.forward_fill) {
        forward_fill(mat, stock_blocks);
    }

    // 2. Winsorization
    if (config_.apply_winsorize) {
        for (int c = 0; c < n_cols; ++c) {
            auto [lo, hi] = winsor_bounds(feature_names[c]);
            winsorize(mat, c, lo, hi, date_idx);
        }
    }

    // 3. Neutralization
    if (config_.neutralize_industry || config_.neutralize_market_cap) {
        // Build industry and market cap vectors
        std::vector<SWIndustry> industries(mat.rows(), SWIndustry::kUnknown);
        Eigen::VectorXd log_mktcaps(mat.rows());
        log_mktcaps.setConstant(std::numeric_limits<double>::quiet_NaN());

        for (int r = 0; r < static_cast<int>(mat.rows()); ++r) {
            auto it = instruments.find(symbols[r]);
            if (it != instruments.end()) {
                industries[r] = it->second.industry;
                if (it->second.total_shares > 0) {
                    // Use a placeholder market cap based on available data
                    log_mktcaps(r) = std::log(static_cast<double>(it->second.total_shares));
                }
            }
        }

        for (int c = 0; c < n_cols; ++c) {
            neutralize(mat, c, industries, log_mktcaps, date_idx);
        }
    }

    // 4. Standardization
    if (config_.apply_standardize) {
        for (int c = 0; c < n_cols; ++c) {
            if (config_.mode == PreprocessorConfig::StandardizeMode::kZScore) {
                standardize_zscore(mat, c, date_idx);
            } else {
                standardize_quantile_rank(mat, c, date_idx);
            }
        }
    }

    // 5. Append missing flags if requested
    if (config_.add_is_missing_flag && missing_flags.cols() > 0) {
        int old_cols = static_cast<int>(mat.cols());
        Eigen::MatrixXd combined(mat.rows(), old_cols + missing_flags.cols());
        combined.leftCols(old_cols) = mat;
        combined.rightCols(missing_flags.cols()) = missing_flags;
        mat = std::move(combined);

        for (int c = 0; c < static_cast<int>(missing_flags.cols()); ++c) {
            feature_names.push_back(feature_names[c] + "_is_missing");
        }
    }

    return mat;
}

} // namespace trade
