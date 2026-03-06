#include "trade/features/feature_monitor.h"
#include <algorithm>
#include <cmath>
#include <numeric>

namespace trade {

// ============================================================================
// Constructors
// ============================================================================

FeatureMonitor::FeatureMonitor() : config_{} {}
FeatureMonitor::FeatureMonitor(Config cfg) : config_(std::move(cfg)) {}

// ============================================================================
// Static computation helpers
// ============================================================================

double FeatureMonitor::pearson_ic(
    const Eigen::VectorXd& feature,
    const Eigen::VectorXd& forward_return) {
    int n = static_cast<int>(feature.size());
    if (n != static_cast<int>(forward_return.size()) || n < 3) return 0.0;

    // Collect valid (non-NaN) pairs
    double sum_x = 0, sum_y = 0, sum_xx = 0, sum_yy = 0, sum_xy = 0;
    int count = 0;
    for (int i = 0; i < n; ++i) {
        if (!std::isnan(feature(i)) && !std::isnan(forward_return(i))) {
            double x = feature(i);
            double y = forward_return(i);
            sum_x += x;
            sum_y += y;
            sum_xx += x * x;
            sum_yy += y * y;
            sum_xy += x * y;
            ++count;
        }
    }
    if (count < 3) return 0.0;

    double mean_x = sum_x / count;
    double mean_y = sum_y / count;
    double var_x = sum_xx / count - mean_x * mean_x;
    double var_y = sum_yy / count - mean_y * mean_y;

    if (var_x <= 1e-15 || var_y <= 1e-15) return 0.0;

    double cov_xy = sum_xy / count - mean_x * mean_y;
    return cov_xy / (std::sqrt(var_x) * std::sqrt(var_y));
}

double FeatureMonitor::spearman_rank_ic(
    const Eigen::VectorXd& feature,
    const Eigen::VectorXd& forward_return) {
    int n = static_cast<int>(feature.size());
    if (n != static_cast<int>(forward_return.size()) || n < 3) return 0.0;

    // Collect valid pairs
    std::vector<int> valid;
    valid.reserve(n);
    for (int i = 0; i < n; ++i) {
        if (!std::isnan(feature(i)) && !std::isnan(forward_return(i))) {
            valid.push_back(i);
        }
    }
    int count = static_cast<int>(valid.size());
    if (count < 3) return 0.0;

    // Rank the feature values
    auto rank_vec = [&](const Eigen::VectorXd& v) -> Eigen::VectorXd {
        std::vector<int> order(count);
        std::iota(order.begin(), order.end(), 0);
        std::sort(order.begin(), order.end(),
                  [&](int a, int b) { return v(valid[a]) < v(valid[b]); });

        Eigen::VectorXd ranks(count);
        for (int i = 0; i < count; ++i) {
            ranks(order[i]) = static_cast<double>(i);
        }
        return ranks;
    };

    auto rank_feat = rank_vec(feature);
    auto rank_ret = rank_vec(forward_return);

    // Pearson correlation on the ranks
    double sum_x = 0, sum_y = 0, sum_xx = 0, sum_yy = 0, sum_xy = 0;
    for (int i = 0; i < count; ++i) {
        double x = rank_feat(i);
        double y = rank_ret(i);
        sum_x += x;
        sum_y += y;
        sum_xx += x * x;
        sum_yy += y * y;
        sum_xy += x * y;
    }

    double mean_x = sum_x / count;
    double mean_y = sum_y / count;
    double var_x = sum_xx / count - mean_x * mean_x;
    double var_y = sum_yy / count - mean_y * mean_y;

    if (var_x <= 1e-15 || var_y <= 1e-15) return 0.0;

    double cov_xy = sum_xy / count - mean_x * mean_y;
    return cov_xy / (std::sqrt(var_x) * std::sqrt(var_y));
}

double FeatureMonitor::compute_ic_ir(const Eigen::VectorXd& ic_series) {
    int n = static_cast<int>(ic_series.size());
    if (n < 2) return 0.0;

    // Filter out NaN
    double sum = 0, sum2 = 0;
    int count = 0;
    for (int i = 0; i < n; ++i) {
        if (!std::isnan(ic_series(i))) {
            sum += ic_series(i);
            sum2 += ic_series(i) * ic_series(i);
            ++count;
        }
    }
    if (count < 2) return 0.0;

    double mean = sum / count;
    double var = (sum2 / count) - mean * mean;
    if (var <= 1e-15) return 0.0;

    return mean / std::sqrt(var);
}

std::pair<double, double> FeatureMonitor::ic_trend_test(
    const Eigen::VectorXd& ic_series) {
    int n = static_cast<int>(ic_series.size());
    if (n < 5) return {0.0, 1.0};

    // Collect valid data points
    std::vector<double> x_vals, y_vals;
    x_vals.reserve(n);
    y_vals.reserve(n);
    for (int i = 0; i < n; ++i) {
        if (!std::isnan(ic_series(i))) {
            x_vals.push_back(static_cast<double>(i));
            y_vals.push_back(ic_series(i));
        }
    }

    int count = static_cast<int>(x_vals.size());
    if (count < 5) return {0.0, 1.0};

    // Simple linear regression: y = a + b*x
    double sum_x = 0, sum_y = 0, sum_xx = 0, sum_xy = 0;
    for (int i = 0; i < count; ++i) {
        sum_x += x_vals[i];
        sum_y += y_vals[i];
        sum_xx += x_vals[i] * x_vals[i];
        sum_xy += x_vals[i] * y_vals[i];
    }

    double mean_x = sum_x / count;
    double mean_y = sum_y / count;
    double var_x = sum_xx / count - mean_x * mean_x;

    if (var_x <= 1e-15) return {0.0, 1.0};

    double slope = (sum_xy / count - mean_x * mean_y) / var_x;
    double intercept = mean_y - slope * mean_x;

    // Compute residual variance for t-test on slope
    double ssr = 0;
    for (int i = 0; i < count; ++i) {
        double pred = intercept + slope * x_vals[i];
        double resid = y_vals[i] - pred;
        ssr += resid * resid;
    }
    double residual_var = ssr / (count - 2);
    double se_slope = std::sqrt(residual_var / (count * var_x));

    if (se_slope <= 1e-15) return {slope, 0.0};

    double t_stat = slope / se_slope;

    // Approximate p-value for one-sided test (slope < 0)
    // Using the approximation: p ~ exp(-0.717*|t| - 0.416*t^2) for df > 20
    // For a proper implementation, use a t-distribution CDF
    double abs_t = std::abs(t_stat);
    double p_value;
    if (count > 30) {
        // Normal approximation
        // erfc(|t|/sqrt(2)) / 2
        p_value = 0.5 * std::erfc(abs_t / std::sqrt(2.0));
    } else {
        // Crude approximation for small samples
        p_value = std::exp(-0.5 * abs_t * abs_t) * 0.5;
        if (count < 10) p_value *= 2.0;  // correction for very small samples
    }

    // One-sided: we test if slope < 0
    if (slope > 0) p_value = 1.0 - p_value;

    return {slope, std::min(1.0, p_value)};
}

double FeatureMonitor::long_short_net_return(
    const Eigen::VectorXd& feature,
    const Eigen::VectorXd& forward_return,
    double one_way_cost) {
    int n = static_cast<int>(feature.size());
    if (n != static_cast<int>(forward_return.size()) || n < 10) return 0.0;

    // Collect valid pairs
    struct Pair {
        double feat;
        double ret;
    };
    std::vector<Pair> valid;
    valid.reserve(n);
    for (int i = 0; i < n; ++i) {
        if (!std::isnan(feature(i)) && !std::isnan(forward_return(i))) {
            valid.push_back({feature(i), forward_return(i)});
        }
    }

    int count = static_cast<int>(valid.size());
    if (count < 10) return 0.0;

    // Sort by feature value
    std::sort(valid.begin(), valid.end(),
              [](const Pair& a, const Pair& b) { return a.feat < b.feat; });

    // Top and bottom quintile
    int q_size = count / 5;
    if (q_size < 1) q_size = 1;

    double long_ret = 0;   // top quintile (highest feature)
    double short_ret = 0;  // bottom quintile (lowest feature)

    for (int i = 0; i < q_size; ++i) {
        short_ret += valid[i].ret;
    }
    for (int i = count - q_size; i < count; ++i) {
        long_ret += valid[i].ret;
    }

    long_ret /= q_size;
    short_ret /= q_size;

    // Long-short return minus 2-way cost (enter + exit on both legs)
    return (long_ret - short_ret) - 4.0 * one_way_cost;
}

bool FeatureMonitor::is_near_zero_window(
    const Eigen::VectorXd& rank_ic_series,
    int window_start, int window_size,
    double threshold) {
    int n = static_cast<int>(rank_ic_series.size());
    int window_end = std::min(window_start + window_size, n);

    if (window_start >= n || window_end <= window_start) return false;

    double sum = 0;
    int count = 0;
    for (int i = window_start; i < window_end; ++i) {
        if (!std::isnan(rank_ic_series(i))) {
            sum += std::abs(rank_ic_series(i));
            ++count;
        }
    }

    if (count == 0) return false;
    double mean_abs_ic = sum / count;
    return mean_abs_ic < threshold;
}

// ============================================================================
// Core API
// ============================================================================

void FeatureMonitor::update(
    const Eigen::MatrixXd& features,
    const Eigen::VectorXd& forward_returns,
    const std::vector<std::string>& feature_names,
    Date eval_date) {

    eval_dates_.push_back(eval_date);
    int n_features = static_cast<int>(feature_names.size());
    int n_stocks = static_cast<int>(features.rows());

    if (n_stocks != static_cast<int>(forward_returns.size())) return;

    for (int f = 0; f < n_features; ++f) {
        const auto& fname = feature_names[f];

        // Initialize health entry if not exists
        if (health_map_.find(fname) == health_map_.end()) {
            FeatureHealth fh;
            fh.feature_name = fname;
            health_map_[fname] = std::move(fh);
        }

        auto& fh = health_map_[fname];

        // Extract feature column
        Eigen::VectorXd feat_col = features.col(f);

        // Compute IC and RankIC for this date
        double ic = pearson_ic(feat_col, forward_returns);
        double ric = spearman_rank_ic(feat_col, forward_returns);

        // Append to IC series
        int old_n = static_cast<int>(fh.ic_series.size());
        Eigen::VectorXd new_ic(old_n + 1);
        Eigen::VectorXd new_ric(old_n + 1);
        if (old_n > 0) {
            new_ic.head(old_n) = fh.ic_series;
            new_ric.head(old_n) = fh.rank_ic_series;
        }
        new_ic(old_n) = ic;
        new_ric(old_n) = ric;
        fh.ic_series = std::move(new_ic);
        fh.rank_ic_series = std::move(new_ric);

        // Update summary statistics
        update_summary(fh, config_.ic_summary_window);

        // Compute long-short net return estimate
        fh.net_of_cost_return_120d = long_short_net_return(
            feat_col, forward_returns, config_.one_way_cost);
    }
}

void FeatureMonitor::update_summary(FeatureHealth& fh, int summary_window) const {
    int n = static_cast<int>(fh.ic_series.size());
    if (n == 0) return;

    // Use last summary_window data points
    int start = std::max(0, n - summary_window);
    int count_ic = 0, count_ric = 0;
    double sum_ic = 0, sum2_ic = 0;
    double sum_ric = 0, sum2_ric = 0;

    for (int i = start; i < n; ++i) {
        if (!std::isnan(fh.ic_series(i))) {
            sum_ic += fh.ic_series(i);
            sum2_ic += fh.ic_series(i) * fh.ic_series(i);
            ++count_ic;
        }
        if (!std::isnan(fh.rank_ic_series(i))) {
            sum_ric += fh.rank_ic_series(i);
            sum2_ric += fh.rank_ic_series(i) * fh.rank_ic_series(i);
            ++count_ric;
        }
    }

    if (count_ic > 0) {
        fh.mean_ic = sum_ic / count_ic;
        double var = (sum2_ic / count_ic) - fh.mean_ic * fh.mean_ic;
        fh.std_ic = (var > 0) ? std::sqrt(var) : 0.0;
        fh.ic_ir = (fh.std_ic > 1e-10) ? fh.mean_ic / fh.std_ic : 0.0;
    }
    if (count_ric > 0) {
        fh.mean_rank_ic = sum_ric / count_ric;
        double var = (sum2_ric / count_ric) - fh.mean_rank_ic * fh.mean_rank_ic;
        fh.std_rank_ic = (var > 0) ? std::sqrt(var) : 0.0;
        fh.rank_ic_ir = (fh.std_rank_ic > 1e-10) ? fh.mean_rank_ic / fh.std_rank_ic : 0.0;
    }

    // Decay detection
    int decay_n = std::min(n, config_.decay_lookback);
    if (decay_n >= 5) {
        Eigen::VectorXd tail = fh.ic_series.tail(decay_n);
        auto [slope, pvalue] = ic_trend_test(tail);
        fh.ic_trend_slope = slope;
        fh.ic_trend_pvalue = pvalue;
        fh.is_decaying = (slope < 0 && pvalue < config_.decay_pvalue_threshold);
    }

    // Near-zero window counting
    int ws = config_.near_zero_window_size;
    if (n >= ws) {
        // Check the last N consecutive windows
        int max_consec = 0;
        int consec = 0;
        int num_windows = n / ws;
        for (int w = 0; w < num_windows; ++w) {
            int wstart = n - (num_windows - w) * ws;
            if (wstart < 0) wstart = 0;
            if (is_near_zero_window(fh.rank_ic_series, wstart, ws,
                                    config_.near_zero_ic_threshold)) {
                ++consec;
                max_consec = std::max(max_consec, consec);
            } else {
                consec = 0;
            }
        }
        fh.consecutive_near_zero_windows = max_consec;
    }
}

void FeatureMonitor::evaluate(Regime current_regime) {
    for (auto& [name, fh] : health_map_) {
        if (fh.is_retired) continue;

        if (check_retirement(fh, current_regime)) {
            fh.is_retired = true;
            fh.retirement_reason = "";

            // Build retirement reason string
            if (fh.consecutive_near_zero_windows >= config_.near_zero_consecutive_req) {
                fh.retirement_reason += "near_zero_ic;";
            }
            if (std::abs(fh.ic_ir) < config_.min_ic_ir) {
                fh.retirement_reason += "low_ic_ir;";
            }
            if (fh.net_of_cost_return_120d < config_.min_net_return) {
                fh.retirement_reason += "negative_net_return;";
            }
            if (fh.is_decaying) {
                fh.retirement_reason += "decaying;";
            }
        }
    }
}

bool FeatureMonitor::check_retirement(const FeatureHealth& fh, Regime regime) const {
    // Rule 1: 3 consecutive 60-day windows with |mean_RankIC| < threshold
    bool near_zero = (fh.consecutive_near_zero_windows >= config_.near_zero_consecutive_req);

    // Rule 2: IC_IR over summary window < min threshold
    bool low_ic_ir = (std::abs(fh.ic_ir) < config_.min_ic_ir);

    // Rule 3: Net-of-cost return is negative over 120d
    bool neg_return = (fh.net_of_cost_return_120d < config_.min_net_return);

    // Rule 4: Not in the factor's best regime
    bool not_best_regime = true;
    auto it = best_regime_.find(fh.feature_name);
    if (it != best_regime_.end()) {
        not_best_regime = (regime != it->second);
    }

    // All four conditions must hold
    return near_zero && low_ic_ir && neg_return && not_best_regime;
}

// ============================================================================
// Accessors (already implemented in stub but included for completeness)
// ============================================================================

const FeatureHealth& FeatureMonitor::health(const std::string& name) const {
    static FeatureHealth empty;
    auto it = health_map_.find(name);
    if (it != health_map_.end()) return it->second;
    return empty;
}

std::vector<std::string> FeatureMonitor::retired_features() const {
    std::vector<std::string> result;
    for (const auto& [name, fh] : health_map_) {
        if (fh.is_retired) result.push_back(name);
    }
    return result;
}

std::vector<std::string> FeatureMonitor::active_features() const {
    std::vector<std::string> result;
    for (const auto& [name, fh] : health_map_) {
        if (!fh.is_retired) result.push_back(name);
    }
    return result;
}

void FeatureMonitor::reinstate(const std::string& name) {
    auto it = health_map_.find(name);
    if (it != health_map_.end()) {
        it->second.is_retired = false;
        it->second.retirement_reason.clear();
        it->second.consecutive_near_zero_windows = 0;
    }
}

std::vector<FeatureHealth> FeatureMonitor::report() const {
    std::vector<FeatureHealth> result;
    result.reserve(health_map_.size());
    for (const auto& [name, fh] : health_map_) {
        result.push_back(fh);
    }
    return result;
}

} // namespace trade
