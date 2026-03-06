#include "trade/features/feature_engine.h"
#include <spdlog/spdlog.h>
#include <algorithm>
#include <cmath>
#include <numeric>

namespace trade {

// ============================================================================
// Utility functions
// ============================================================================

Eigen::VectorXd cs_rank(const Eigen::VectorXd& v) {
    int n = static_cast<int>(v.size());
    Eigen::VectorXd ranks(n);
    ranks.setConstant(std::numeric_limits<double>::quiet_NaN());

    std::vector<int> valid;
    valid.reserve(n);
    for (int i = 0; i < n; ++i) {
        if (!std::isnan(v(i))) valid.push_back(i);
    }
    if (valid.empty()) return ranks;

    std::sort(valid.begin(), valid.end(),
              [&](int a, int b) { return v(a) < v(b); });

    double denom = static_cast<double>(valid.size()) - 1.0;
    if (denom <= 0) denom = 1.0;
    for (int i = 0; i < static_cast<int>(valid.size()); ++i) {
        ranks(valid[i]) = static_cast<double>(i) / denom;
    }
    return ranks;
}

Eigen::VectorXd ts_zscore(const Eigen::VectorXd& v, int lookback) {
    int n = static_cast<int>(v.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    for (int i = lookback - 1; i < n; ++i) {
        int count = 0;
        double sum = 0, sum2 = 0;
        for (int j = i - lookback + 1; j <= i; ++j) {
            if (!std::isnan(v(j))) {
                sum += v(j);
                sum2 += v(j) * v(j);
                ++count;
            }
        }
        if (count < 2) continue;
        double mean = sum / count;
        double var = (sum2 / count) - mean * mean;
        if (var <= 0) continue;
        double std_dev = std::sqrt(var);
        if (!std::isnan(v(i))) {
            result(i) = (v(i) - mean) / std_dev;
        }
    }
    return result;
}

Eigen::VectorXd ewma(const Eigen::VectorXd& v, int halflife) {
    int n = static_cast<int>(v.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    double alpha = 1.0 - std::exp(-std::log(2.0) / halflife);
    bool initialized = false;
    double ema_val = 0;

    for (int i = 0; i < n; ++i) {
        if (std::isnan(v(i))) {
            if (initialized) result(i) = ema_val;
            continue;
        }
        if (!initialized) {
            ema_val = v(i);
            initialized = true;
        } else {
            ema_val = alpha * v(i) + (1.0 - alpha) * ema_val;
        }
        result(i) = ema_val;
    }
    return result;
}

Eigen::VectorXd rolling_mean(const Eigen::VectorXd& v, int window) {
    int n = static_cast<int>(v.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    for (int i = window - 1; i < n; ++i) {
        double sum = 0;
        int count = 0;
        for (int j = i - window + 1; j <= i; ++j) {
            if (!std::isnan(v(j))) {
                sum += v(j);
                ++count;
            }
        }
        if (count > 0) result(i) = sum / count;
    }
    return result;
}

Eigen::VectorXd rolling_std(const Eigen::VectorXd& v, int window) {
    int n = static_cast<int>(v.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    for (int i = window - 1; i < n; ++i) {
        double sum = 0, sum2 = 0;
        int count = 0;
        for (int j = i - window + 1; j <= i; ++j) {
            if (!std::isnan(v(j))) {
                sum += v(j);
                sum2 += v(j) * v(j);
                ++count;
            }
        }
        if (count < 2) continue;
        double mean = sum / count;
        double var = (sum2 - count * mean * mean) / (count - 1);
        if (var > 0) result(i) = std::sqrt(var);
    }
    return result;
}

Eigen::VectorXd rolling_sum(const Eigen::VectorXd& v, int window) {
    int n = static_cast<int>(v.size());
    Eigen::VectorXd result(n);
    result.setConstant(std::numeric_limits<double>::quiet_NaN());

    for (int i = window - 1; i < n; ++i) {
        double sum = 0;
        int count = 0;
        for (int j = i - window + 1; j <= i; ++j) {
            if (!std::isnan(v(j))) {
                sum += v(j);
                ++count;
            }
        }
        if (count > 0) result(i) = sum;
    }
    return result;
}

// ============================================================================
// FeatureEngine
// ============================================================================

FeatureEngine::FeatureEngine() : config_{} {}
FeatureEngine::FeatureEngine(Config cfg) : config_(std::move(cfg)) {}

void FeatureEngine::register_calculator(std::unique_ptr<FeatureCalculator> calc) {
    spdlog::debug("Registered feature calculator: {}", calc->group_name());
    calculators_.push_back(std::move(calc));
}

FeatureSet FeatureEngine::compute_raw(
    const std::vector<BarSeries>& series,
    const std::unordered_map<Symbol, Instrument>& instruments) const {

    FeatureSet merged;
    for (const auto& calc : calculators_) {
        spdlog::debug("Computing features: {}", calc->group_name());
        auto fs = calc->compute(series, instruments);
        if (fs.matrix.rows() == 0) continue;

        if (merged.matrix.rows() == 0) {
            merged = std::move(fs);
        } else {
            merged.merge(fs);
        }
    }
    spdlog::info("Computed {} raw features for {} observations",
                 merged.num_features(), merged.num_observations());
    return merged;
}

FeatureSet FeatureEngine::preprocess(
    const FeatureSet& raw,
    const std::unordered_map<Symbol, Instrument>& instruments) const {

    if (!config_.fill_missing && !config_.winsorize &&
        !config_.neutralize && !config_.standardize) {
        return raw;
    }

    PreprocessorConfig pp_cfg;
    pp_cfg.forward_fill = config_.fill_missing;
    pp_cfg.add_is_missing_flag = config_.fill_missing;
    pp_cfg.apply_winsorize = config_.winsorize;
    pp_cfg.neutralize_industry = config_.neutralize;
    pp_cfg.neutralize_market_cap = config_.neutralize;
    pp_cfg.apply_standardize = config_.standardize;
    pp_cfg.mode = config_.standardize_mode;

    Preprocessor pp(pp_cfg);

    FeatureSet result;
    result.symbols = raw.symbols;
    result.dates = raw.dates;
    result.names = raw.names;
    result.matrix = pp.run(raw.matrix, result.names,
                           raw.symbols, raw.dates, instruments);
    return result;
}

FeatureSet FeatureEngine::build(
    const std::vector<BarSeries>& series,
    const std::unordered_map<Symbol, Instrument>& instruments) const {
    auto raw = compute_raw(series, instruments);
    return preprocess(raw, instruments);
}

} // namespace trade
