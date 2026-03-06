#pragma once

#include "trade/model/bar.h"
#include "trade/model/instrument.h"
#include "trade/model/market.h"
#include "trade/features/preprocessor.h"

#include <Eigen/Dense>
#include <functional>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace trade {

// ============================================================================
// FeatureSet: named matrix of computed features
// ============================================================================
// Rows = observations (stocks at a given date), Cols = feature dimensions.
// |names| has the same length as the number of columns in |matrix|.
struct FeatureSet {
    std::vector<std::string> names;          // column names
    std::vector<Symbol> symbols;             // row labels (one per stock)
    std::vector<Date> dates;                 // date for each row (panel data)
    Eigen::MatrixXd matrix;                  // (num_observations x num_features)

    int num_features() const { return static_cast<int>(names.size()); }
    int num_observations() const { return static_cast<int>(matrix.rows()); }

    // Lookup column index by name, returns -1 if not found
    int col_index(const std::string& name) const {
        for (int i = 0; i < static_cast<int>(names.size()); ++i) {
            if (names[i] == name) return i;
        }
        return -1;
    }

    // Extract a single feature column
    Eigen::VectorXd column(const std::string& name) const {
        int idx = col_index(name);
        if (idx < 0) return Eigen::VectorXd();
        return matrix.col(idx);
    }

    // Append another FeatureSet column-wise (must have same rows)
    void merge(const FeatureSet& other) {
        if (other.matrix.rows() != matrix.rows() && matrix.rows() != 0) return;
        int old_cols = static_cast<int>(matrix.cols());
        int new_cols = old_cols + static_cast<int>(other.matrix.cols());
        Eigen::MatrixXd merged(other.matrix.rows(), new_cols);
        if (old_cols > 0) merged.leftCols(old_cols) = matrix;
        merged.rightCols(other.matrix.cols()) = other.matrix;
        matrix = std::move(merged);
        names.insert(names.end(), other.names.begin(), other.names.end());
    }
};

// ============================================================================
// FeatureCalculator: base interface for individual feature groups
// ============================================================================
// Each feature group (momentum, volatility, etc.) implements this interface.
class FeatureCalculator {
public:
    virtual ~FeatureCalculator() = default;

    // Human-readable group name, e.g. "momentum", "volatility"
    virtual std::string group_name() const = 0;

    // Compute raw features for all stocks over the given panel.
    // Returns a FeatureSet whose rows are (stock x date) observations.
    virtual FeatureSet compute(
        const std::vector<BarSeries>& series,
        const std::unordered_map<Symbol, Instrument>& instruments) const = 0;
};

// ============================================================================
// FeatureEngine: orchestrates the full feature pipeline
// ============================================================================
//   1. Register feature calculators (momentum, vol, liquidity, ...)
//   2. compute_raw()  -- runs every calculator, column-merges results
//   3. preprocess()   -- fill missing, winsorize, neutralize, standardize
//   4. build()        -- convenience: compute_raw -> preprocess -> output
//
class FeatureEngine {
public:
    // --- Configuration ---------------------------------------------------

    struct Config {
        // Preprocessing toggles
        bool fill_missing = true;
        bool winsorize = true;
        bool neutralize = true;
        bool standardize = true;

        // Standardization mode
        PreprocessorConfig::StandardizeMode standardize_mode =
            PreprocessorConfig::StandardizeMode::kZScore;

        // Minimum number of bars required per stock before computing features
        int min_bar_count = 120;
    };

    FeatureEngine();
    explicit FeatureEngine(Config cfg);

    FeatureEngine(const FeatureEngine&) = delete;
    FeatureEngine& operator=(const FeatureEngine&) = delete;
    FeatureEngine(FeatureEngine&&) = default;
    FeatureEngine& operator=(FeatureEngine&&) = default;

    // --- Registration ----------------------------------------------------

    // Register a calculator; ownership is transferred.
    void register_calculator(std::unique_ptr<FeatureCalculator> calc);

    // Convenience: register by constructing in-place
    template <typename T, typename... Args>
    void emplace_calculator(Args&&... args) {
        register_calculator(std::make_unique<T>(std::forward<Args>(args)...));
    }

    // --- Pipeline --------------------------------------------------------

    // Step 1: compute raw features from every registered calculator
    FeatureSet compute_raw(
        const std::vector<BarSeries>& series,
        const std::unordered_map<Symbol, Instrument>& instruments) const;

    // Step 2: apply preprocessing pipeline to a raw FeatureSet
    FeatureSet preprocess(
        const FeatureSet& raw,
        const std::unordered_map<Symbol, Instrument>& instruments) const;

    // Full pipeline: compute_raw -> preprocess -> return
    FeatureSet build(
        const std::vector<BarSeries>& series,
        const std::unordered_map<Symbol, Instrument>& instruments) const;

    // --- Accessors -------------------------------------------------------

    const std::vector<std::unique_ptr<FeatureCalculator>>& calculators() const {
        return calculators_;
    }

    const Config& config() const { return config_; }

private:
    Config config_;
    std::vector<std::unique_ptr<FeatureCalculator>> calculators_;
};

// ============================================================================
// Cross-sectional & time-series transform utilities
// ============================================================================

// Cross-sectional rank within a single date slice.
// Input:  (N,) vector of raw values for N stocks.
// Output: (N,) vector of fractional ranks in [0, 1]. NaN stays NaN.
Eigen::VectorXd cs_rank(const Eigen::VectorXd& v);

// Time-series z-score for a single stock over its history.
// Input:  (T,) vector of a feature across T dates.
// Output: (T,) vector of (x - mean) / std.  NaN if std == 0.
Eigen::VectorXd ts_zscore(const Eigen::VectorXd& v, int lookback);

// Exponentially weighted moving average
Eigen::VectorXd ewma(const Eigen::VectorXd& v, int halflife);

// Rolling window mean
Eigen::VectorXd rolling_mean(const Eigen::VectorXd& v, int window);

// Rolling window standard deviation
Eigen::VectorXd rolling_std(const Eigen::VectorXd& v, int window);

// Rolling sum
Eigen::VectorXd rolling_sum(const Eigen::VectorXd& v, int window);

} // namespace trade
