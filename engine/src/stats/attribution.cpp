#include "trade/stats/attribution.h"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <unordered_set>
#include <sstream>

namespace trade {

// ===========================================================================
// Brinson-Fachler Attribution
// ===========================================================================

BrinsonResult ReturnAttribution::brinson_attribution(
    const std::unordered_map<Symbol, double>& portfolio_weights,
    const std::unordered_map<Symbol, double>& benchmark_weights,
    const std::unordered_map<Symbol, double>& stock_returns,
    const std::unordered_map<Symbol, Instrument>& instruments,
    Date start, Date end) {

    BrinsonResult result;
    result.start_date = start;
    result.end_date = end;

    // -----------------------------------------------------------------------
    // Step 1: Gather the universe of all industries present in either
    //         portfolio or benchmark.
    // -----------------------------------------------------------------------
    std::unordered_set<uint8_t> industry_set;
    auto get_industry = [&](const Symbol& sym) -> SWIndustry {
        auto it = instruments.find(sym);
        return (it != instruments.end()) ? it->second.industry : SWIndustry::kUnknown;
    };

    for (const auto& [sym, w] : portfolio_weights) {
        industry_set.insert(static_cast<uint8_t>(get_industry(sym)));
    }
    for (const auto& [sym, w] : benchmark_weights) {
        industry_set.insert(static_cast<uint8_t>(get_industry(sym)));
    }

    // -----------------------------------------------------------------------
    // Step 2: For each industry, compute:
    //   w_p_j  = portfolio weight in industry j
    //   w_b_j  = benchmark weight in industry j
    //   r_p_j  = portfolio return within industry j (weighted by intra-industry weights)
    //   r_b_j  = benchmark return within industry j
    // -----------------------------------------------------------------------

    struct IndustryAccum {
        double port_weight = 0.0;
        double bench_weight = 0.0;
        double port_weighted_ret = 0.0;  // sum of w_i * r_i for portfolio stocks in this industry
        double bench_weighted_ret = 0.0; // same for benchmark
    };
    std::unordered_map<uint8_t, IndustryAccum> industry_accum;

    // Initialize accumulators
    for (uint8_t ind : industry_set) {
        industry_accum[ind] = {};
    }

    // Accumulate portfolio
    for (const auto& [sym, w] : portfolio_weights) {
        uint8_t ind = static_cast<uint8_t>(get_industry(sym));
        auto ret_it = stock_returns.find(sym);
        double ret = (ret_it != stock_returns.end()) ? ret_it->second : 0.0;
        industry_accum[ind].port_weight += w;
        industry_accum[ind].port_weighted_ret += w * ret;
    }

    // Accumulate benchmark
    for (const auto& [sym, w] : benchmark_weights) {
        uint8_t ind = static_cast<uint8_t>(get_industry(sym));
        auto ret_it = stock_returns.find(sym);
        double ret = (ret_it != stock_returns.end()) ? ret_it->second : 0.0;
        industry_accum[ind].bench_weight += w;
        industry_accum[ind].bench_weighted_ret += w * ret;
    }

    // -----------------------------------------------------------------------
    // Step 3: Compute total portfolio & benchmark returns, and industry-level
    //         Brinson-Fachler decomposition.
    // -----------------------------------------------------------------------

    result.total_return = 0.0;
    result.benchmark_return = 0.0;

    for (const auto& [ind, acc] : industry_accum) {
        result.total_return += acc.port_weighted_ret;
        result.benchmark_return += acc.bench_weighted_ret;
    }
    result.active_return = result.total_return - result.benchmark_return;

    // Per-industry detail and aggregate effects
    double total_allocation = 0.0;
    double total_selection = 0.0;
    double total_interaction = 0.0;

    for (const auto& [ind, acc] : industry_accum) {
        BrinsonResult::IndustryDetail detail;
        detail.industry = static_cast<SWIndustry>(ind);
        detail.portfolio_weight = acc.port_weight;
        detail.benchmark_weight = acc.bench_weight;

        // Industry-level returns (weight-normalised within industry)
        detail.portfolio_return = (acc.port_weight > 1e-15)
            ? acc.port_weighted_ret / acc.port_weight : 0.0;
        detail.benchmark_return = (acc.bench_weight > 1e-15)
            ? acc.bench_weighted_ret / acc.bench_weight : 0.0;

        // Brinson-Fachler decomposition:
        //   Allocation_j  = (w_p_j - w_b_j) * (r_b_j - R_b)
        //   Selection_j   = w_b_j * (r_p_j - r_b_j)
        //   Interaction_j = (w_p_j - w_b_j) * (r_p_j - r_b_j)
        double delta_w = detail.portfolio_weight - detail.benchmark_weight;
        double delta_r = detail.portfolio_return - detail.benchmark_return;

        detail.allocation = delta_w * (detail.benchmark_return - result.benchmark_return);
        detail.selection = detail.benchmark_weight * delta_r;
        detail.interaction = delta_w * delta_r;

        total_allocation += detail.allocation;
        total_selection += detail.selection;
        total_interaction += detail.interaction;

        result.industry_details.push_back(detail);
    }

    result.allocation_effect = total_allocation;
    result.selection_effect = total_selection;
    result.interaction_effect = total_interaction;

    // Sort industry_details by industry code for consistent output
    std::sort(result.industry_details.begin(), result.industry_details.end(),
              [](const BrinsonResult::IndustryDetail& a,
                 const BrinsonResult::IndustryDetail& b) {
                  return static_cast<uint8_t>(a.industry) < static_cast<uint8_t>(b.industry);
              });

    return result;
}

// ===========================================================================
// Factor Attribution
// ===========================================================================

FactorAttributionResult ReturnAttribution::factor_attribution(
    const std::unordered_map<Symbol, double>& portfolio_weights,
    const Eigen::MatrixXd& factor_exposures,
    const Eigen::VectorXd& factor_returns,
    const std::vector<Symbol>& symbols,
    const std::vector<std::string>& factor_names,
    double total_return,
    Date start, Date end) {

    FactorAttributionResult result;
    result.start_date = start;
    result.end_date = end;
    result.total_return = total_return;

    int N = static_cast<int>(symbols.size());
    int K = static_cast<int>(factor_names.size());

    if (N == 0 || K == 0) {
        result.factor_return = 0.0;
        result.specific_return = total_return;
        return result;
    }

    // Build portfolio weight vector aligned with symbols
    Eigen::VectorXd w(N);
    for (int i = 0; i < N; ++i) {
        auto it = portfolio_weights.find(symbols[i]);
        w(i) = (it != portfolio_weights.end()) ? it->second : 0.0;
    }

    // Portfolio factor exposure = w^T * factor_exposures (1 x K)
    // factor_exposures is N x K
    Eigen::VectorXd port_exposure = factor_exposures.transpose() * w;  // K x 1

    // Factor contributions
    double sum_factor = 0.0;
    result.factors.resize(K);
    for (int k = 0; k < K; ++k) {
        result.factors[k].factor_name = factor_names[k];
        result.factors[k].exposure = port_exposure(k);
        result.factors[k].factor_return = factor_returns(k);
        result.factors[k].contribution = port_exposure(k) * factor_returns(k);
        sum_factor += result.factors[k].contribution;
    }

    result.factor_return = sum_factor;
    result.specific_return = total_return - sum_factor;

    return result;
}

// ===========================================================================
// Anomaly Detection: Volume Spikes
// ===========================================================================

std::vector<Anomaly> ReturnAttribution::detect_volume_spikes(
    const BarSeries& series, int lookback, double threshold) {

    std::vector<Anomaly> anomalies;
    int n = static_cast<int>(series.bars.size());
    if (n < lookback + 1) return anomalies;

    for (int i = lookback; i < n; ++i) {
        // Compute rolling mean and std of volume over [i-lookback, i-1]
        double sum = 0.0;
        double sum_sq = 0.0;
        for (int j = i - lookback; j < i; ++j) {
            double v = static_cast<double>(series.bars[j].volume);
            sum += v;
            sum_sq += v * v;
        }
        double mean = sum / static_cast<double>(lookback);
        double var = sum_sq / static_cast<double>(lookback) - mean * mean;
        double std_dev = std::sqrt(std::max(var, 0.0));

        double current_vol = static_cast<double>(series.bars[i].volume);
        double z = (std_dev > 1e-10) ? (current_vol - mean) / std_dev : 0.0;

        if (z > threshold) {
            Anomaly a;
            a.symbol = series.symbol;
            a.date = series.bars[i].date;
            a.type = AnomalyType::kVolumeSpike;
            a.observed_value = current_vol;
            a.threshold = mean + threshold * std_dev;
            a.z_score = z;
            a.description = "Volume spike: " + std::to_string(static_cast<long long>(current_vol))
                            + " vs rolling mean " + std::to_string(static_cast<long long>(mean));
            anomalies.push_back(a);
        }
    }

    return anomalies;
}

// ===========================================================================
// Anomaly Detection: Price Gaps
// ===========================================================================

std::vector<Anomaly> ReturnAttribution::detect_price_gaps(
    const BarSeries& series, double threshold) {

    std::vector<Anomaly> anomalies;
    int n = static_cast<int>(series.bars.size());

    for (int i = 0; i < n; ++i) {
        const Bar& bar = series.bars[i];
        if (bar.prev_close <= 0.0) continue;

        double gap = (bar.open - bar.prev_close) / bar.prev_close;

        if (gap > threshold) {
            Anomaly a;
            a.symbol = series.symbol;
            a.date = bar.date;
            a.type = AnomalyType::kPriceGapUp;
            a.observed_value = gap;
            a.threshold = threshold;
            a.z_score = gap / threshold;
            a.description = "Price gap up: " + std::to_string(gap * 100.0) + "%";
            anomalies.push_back(a);
        } else if (gap < -threshold) {
            Anomaly a;
            a.symbol = series.symbol;
            a.date = bar.date;
            a.type = AnomalyType::kPriceGapDown;
            a.observed_value = gap;
            a.threshold = -threshold;
            a.z_score = std::abs(gap) / threshold;
            a.description = "Price gap down: " + std::to_string(gap * 100.0) + "%";
            anomalies.push_back(a);
        }
    }

    return anomalies;
}

// ===========================================================================
// Anomaly Detection: Turnover Spikes
// ===========================================================================

std::vector<Anomaly> ReturnAttribution::detect_turnover_spikes(
    const BarSeries& series, int lookback, double threshold) {

    std::vector<Anomaly> anomalies;
    int n = static_cast<int>(series.bars.size());
    if (n < lookback + 1) return anomalies;

    for (int i = lookback; i < n; ++i) {
        double sum = 0.0;
        double sum_sq = 0.0;
        for (int j = i - lookback; j < i; ++j) {
            double tr = series.bars[j].turnover_rate;
            sum += tr;
            sum_sq += tr * tr;
        }
        double mean = sum / static_cast<double>(lookback);
        double var = sum_sq / static_cast<double>(lookback) - mean * mean;
        double std_dev = std::sqrt(std::max(var, 0.0));

        double current_tr = series.bars[i].turnover_rate;
        double z = (std_dev > 1e-10) ? (current_tr - mean) / std_dev : 0.0;

        if (z > threshold) {
            Anomaly a;
            a.symbol = series.symbol;
            a.date = series.bars[i].date;
            a.type = AnomalyType::kTurnoverSpike;
            a.observed_value = current_tr;
            a.threshold = mean + threshold * std_dev;
            a.z_score = z;
            a.description = "Turnover spike: " + std::to_string(current_tr)
                            + " vs rolling mean " + std::to_string(mean);
            anomalies.push_back(a);
        }
    }

    return anomalies;
}

// ===========================================================================
// Anomaly Detection: Volatility Spikes (intraday range)
// ===========================================================================

std::vector<Anomaly> ReturnAttribution::detect_volatility_spikes(
    const BarSeries& series, int lookback, double threshold) {

    std::vector<Anomaly> anomalies;
    int n = static_cast<int>(series.bars.size());
    if (n < lookback + 1) return anomalies;

    for (int i = lookback; i < n; ++i) {
        double sum = 0.0;
        double sum_sq = 0.0;
        for (int j = i - lookback; j < i; ++j) {
            double range = series.bars[j].high - series.bars[j].low;
            sum += range;
            sum_sq += range * range;
        }
        double mean = sum / static_cast<double>(lookback);
        double var = sum_sq / static_cast<double>(lookback) - mean * mean;
        double std_dev = std::sqrt(std::max(var, 0.0));

        double current_range = series.bars[i].high - series.bars[i].low;
        double z = (std_dev > 1e-10) ? (current_range - mean) / std_dev : 0.0;

        if (z > threshold) {
            Anomaly a;
            a.symbol = series.symbol;
            a.date = series.bars[i].date;
            a.type = AnomalyType::kVolatilitySpike;
            a.observed_value = current_range;
            a.threshold = mean + threshold * std_dev;
            a.z_score = z;
            a.description = "Volatility spike: range " + std::to_string(current_range)
                            + " vs rolling mean " + std::to_string(mean);
            anomalies.push_back(a);
        }
    }

    return anomalies;
}

// ===========================================================================
// Detect All Anomalies (merge all detectors)
// ===========================================================================

std::vector<Anomaly> ReturnAttribution::detect_all_anomalies(
    const BarSeries& series, int lookback,
    double spike_threshold, double gap_threshold) {

    auto vol_spikes = detect_volume_spikes(series, lookback, spike_threshold);
    auto gaps = detect_price_gaps(series, gap_threshold);
    auto turnover = detect_turnover_spikes(series, lookback, spike_threshold);
    auto volatility = detect_volatility_spikes(series, lookback, spike_threshold);

    std::vector<Anomaly> all;
    all.reserve(vol_spikes.size() + gaps.size() + turnover.size() + volatility.size());
    all.insert(all.end(), vol_spikes.begin(), vol_spikes.end());
    all.insert(all.end(), gaps.begin(), gaps.end());
    all.insert(all.end(), turnover.begin(), turnover.end());
    all.insert(all.end(), volatility.begin(), volatility.end());

    // Sort by date
    std::sort(all.begin(), all.end(),
              [](const Anomaly& a, const Anomaly& b) {
                  if (a.date != b.date) return a.date < b.date;
                  return a.symbol < b.symbol;
              });

    return all;
}

// ===========================================================================
// Event Labelling: Limit Hits
// ===========================================================================

std::vector<EventTag> ReturnAttribution::label_limit_hits(
    const std::vector<Bar>& bars) {

    std::vector<EventTag> tags;

    for (const auto& bar : bars) {
        if (bar.hit_limit_up) {
            EventTag tag;
            tag.symbol = bar.symbol;
            tag.date = bar.date;
            tag.label = EventLabel::kLimitUpHit;
            tag.detail = "Hit limit up at " + std::to_string(bar.limit_up);
            tags.push_back(tag);
        }
        if (bar.hit_limit_down) {
            EventTag tag;
            tag.symbol = bar.symbol;
            tag.date = bar.date;
            tag.label = EventLabel::kLimitDownHit;
            tag.detail = "Hit limit down at " + std::to_string(bar.limit_down);
            tags.push_back(tag);
        }
    }

    return tags;
}

// ===========================================================================
// Event Labelling: Earnings Windows
// ===========================================================================

std::vector<EventTag> ReturnAttribution::label_earnings_windows(
    const Symbol& symbol,
    const std::vector<Date>& earnings_dates,
    const std::vector<Date>& trading_dates,
    int pre_days, int post_days) {

    std::vector<EventTag> tags;

    if (earnings_dates.empty() || trading_dates.empty()) return tags;

    // Build a set of earnings dates for quick lookup
    std::unordered_set<Date> earnings_set(earnings_dates.begin(), earnings_dates.end());

    // For each trading date, check if it falls within any earnings window.
    // We iterate through trading dates and check distance to each earnings date.
    // For efficiency, we use a two-pointer approach since both are sorted.

    int n_trading = static_cast<int>(trading_dates.size());
    int n_earnings = static_cast<int>(earnings_dates.size());

    for (int e = 0; e < n_earnings; ++e) {
        Date earn_date = earnings_dates[e];

        // Find the index of the earnings date in trading_dates (or nearest)
        auto it = std::lower_bound(trading_dates.begin(), trading_dates.end(), earn_date);
        int earn_idx = static_cast<int>(it - trading_dates.begin());

        // Pre-window: trading days before the earnings date
        for (int d = 1; d <= pre_days; ++d) {
            int idx = earn_idx - d;
            if (idx < 0) break;
            EventTag tag;
            tag.symbol = symbol;
            tag.date = trading_dates[idx];
            tag.label = EventLabel::kEarningsPreWindow;
            tag.detail = "Earnings pre-window: " + std::to_string(d) + " days before announcement";
            tags.push_back(tag);
        }

        // Post-window: trading days after the earnings date (inclusive of the date itself)
        for (int d = 0; d <= post_days; ++d) {
            int idx = earn_idx + d;
            if (idx >= n_trading) break;
            EventTag tag;
            tag.symbol = symbol;
            tag.date = trading_dates[idx];
            tag.label = (d == 0) ? EventLabel::kEarningsPostWindow : EventLabel::kEarningsPostWindow;
            tag.detail = (d == 0) ? "Earnings announcement date"
                                  : "Earnings post-window: " + std::to_string(d) + " days after announcement";
            tags.push_back(tag);
        }
    }

    return tags;
}

// ===========================================================================
// Event Labelling: Policy Dates
// ===========================================================================

std::vector<EventTag> ReturnAttribution::label_policy_dates(
    const Symbol& symbol,
    const std::unordered_map<Date, std::string>& policy_dates,
    const std::vector<Date>& trading_dates) {

    std::vector<EventTag> tags;

    for (const auto& td : trading_dates) {
        auto it = policy_dates.find(td);
        if (it != policy_dates.end()) {
            EventTag tag;
            tag.symbol = symbol;
            tag.date = td;
            tag.label = EventLabel::kPolicyDate;
            tag.detail = it->second;
            tags.push_back(tag);
        }
    }

    return tags;
}

// ===========================================================================
// Event Labelling: Index Rebalance
// ===========================================================================

std::vector<EventTag> ReturnAttribution::label_index_rebalance(
    const Symbol& symbol,
    const std::vector<Date>& rebalance_dates,
    const std::vector<Date>& trading_dates) {

    std::vector<EventTag> tags;

    if (rebalance_dates.empty() || trading_dates.empty()) return tags;

    // Build a set for efficient lookup
    std::unordered_set<Date> rebalance_set(rebalance_dates.begin(), rebalance_dates.end());

    for (const auto& td : trading_dates) {
        if (rebalance_set.count(td)) {
            EventTag tag;
            tag.symbol = symbol;
            tag.date = td;
            tag.label = EventLabel::kIndexRebalance;
            tag.detail = "Index rebalance date";
            tags.push_back(tag);
        }
    }

    return tags;
}

// ===========================================================================
// Merge Events
// ===========================================================================

std::vector<EventTag> ReturnAttribution::merge_events(
    const std::vector<std::vector<EventTag>>& tag_lists) {

    std::vector<EventTag> merged;

    // Count total for reservation
    size_t total = 0;
    for (const auto& list : tag_lists) {
        total += list.size();
    }
    merged.reserve(total);

    for (const auto& list : tag_lists) {
        merged.insert(merged.end(), list.begin(), list.end());
    }

    // Sort by (date, symbol, label)
    std::sort(merged.begin(), merged.end(),
              [](const EventTag& a, const EventTag& b) {
                  if (a.date != b.date) return a.date < b.date;
                  if (a.symbol != b.symbol) return a.symbol < b.symbol;
                  return static_cast<uint8_t>(a.label) < static_cast<uint8_t>(b.label);
              });

    return merged;
}

} // namespace trade
