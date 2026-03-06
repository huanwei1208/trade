#pragma once

#include "trade/common/types.h"
#include "trade/model/instrument.h"

#include <Eigen/Dense>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace trade {

// ============================================================================
// PreprocessorConfig
// ============================================================================

struct PreprocessorConfig {
    // -- Missing value handling -------------------------------------------
    bool forward_fill = true;           // forward-fill NaN gaps per stock
    bool add_is_missing_flag = true;    // append binary is_missing indicator col

    // -- Winsorization ----------------------------------------------------
    // Percentile bounds differ by feature domain:
    //   price/return features : [0.5%, 99.5%]
    //   fundamental features  : [1%,   99%  ]
    double price_lower_pct = 0.005;
    double price_upper_pct = 0.995;
    double fund_lower_pct = 0.01;
    double fund_upper_pct = 0.99;
    bool apply_winsorize = true;

    // Feature names whose winsorization uses fundamental bounds.
    // Everything else uses price bounds.
    std::unordered_set<std::string> fundamental_features = {
        "roe_ttm", "roa_ttm", "ep", "bp",
        "revenue_yoy", "profit_yoy", "fcf_yield",
        "cfo_ni", "accruals", "earnings_surprise"
    };

    // -- Neutralization ---------------------------------------------------
    // Regress out industry (dummy) and log(market-cap) effects, keep residual.
    bool neutralize_industry = true;
    bool neutralize_market_cap = true;

    // -- Standardization --------------------------------------------------
    enum class StandardizeMode {
        kZScore,        // (x - mean) / std   -- suitable for linear models
        kQuantileRank,  // percentile rank [0, 1] -- suitable for tree models
    };
    bool apply_standardize = true;
    StandardizeMode mode = StandardizeMode::kZScore;
};

// ============================================================================
// Preprocessor
// ============================================================================
//
// Usage:
//   Preprocessor pp(config);
//   Eigen::MatrixXd clean = pp.run(raw_matrix, feature_names, symbols, instruments);
//
// The pipeline applies in fixed order:
//   1. Forward-fill missing values  (+ optional is_missing flag)
//   2. Winsorize extreme values
//   3. Industry / market-cap neutralization
//   4. Standardization (z-score or quantile rank)
//
class Preprocessor {
public:
    explicit Preprocessor(PreprocessorConfig cfg = PreprocessorConfig{});

    // Full pipeline: returns a new matrix (may have more columns if
    // is_missing flags are appended).
    // |feature_names| is mutated to include any appended indicator names.
    Eigen::MatrixXd run(
        const Eigen::MatrixXd& raw,
        std::vector<std::string>& feature_names,
        const std::vector<Symbol>& symbols,
        const std::vector<Date>& dates,
        const std::unordered_map<Symbol, Instrument>& instruments) const;

    // --- Individual stages (public for testing) ---------------------------

    // Forward-fill NaN per stock across time (in-place).
    // |stock_blocks| maps each unique symbol to its row indices.
    static void forward_fill(
        Eigen::MatrixXd& mat,
        const std::unordered_map<Symbol, std::vector<int>>& stock_blocks);

    // Create binary is_missing matrix (1 where original was NaN, else 0).
    static Eigen::MatrixXd make_missing_flags(const Eigen::MatrixXd& mat);

    // Winsorize column by percentile bounds (in-place, per cross-section).
    // |date_indices| maps each Date to the row indices in that cross-section.
    static void winsorize(
        Eigen::MatrixXd& mat,
        int col,
        double lower_pct,
        double upper_pct,
        const std::unordered_map<Date, std::vector<int>>& date_indices);

    // Industry + market-cap neutralization for a single column.
    // Within each date cross-section, regress feature on industry dummies
    // and log(market_cap), replace with residuals.
    //
    //   y_i = sum_j (beta_j * I_{industry_j}) + gamma * log(mktcap_i) + eps_i
    //   output_i = eps_i
    //
    // |market_caps| is a vector of doubles aligned with matrix rows.
    // |industries| is a vector of SWIndustry aligned with matrix rows.
    static void neutralize(
        Eigen::MatrixXd& mat,
        int col,
        const std::vector<SWIndustry>& industries,
        const Eigen::VectorXd& log_market_caps,
        const std::unordered_map<Date, std::vector<int>>& date_indices);

    // Z-score standardization within each date cross-section (in-place).
    static void standardize_zscore(
        Eigen::MatrixXd& mat,
        int col,
        const std::unordered_map<Date, std::vector<int>>& date_indices);

    // Quantile-rank standardization within each date cross-section (in-place).
    // Output values in [0, 1].
    static void standardize_quantile_rank(
        Eigen::MatrixXd& mat,
        int col,
        const std::unordered_map<Date, std::vector<int>>& date_indices);

    const PreprocessorConfig& config() const { return config_; }

private:
    PreprocessorConfig config_;

    // Build date -> row index mapping
    static std::unordered_map<Date, std::vector<int>> build_date_index(
        const std::vector<Date>& dates);

    // Build symbol -> row index mapping
    static std::unordered_map<Symbol, std::vector<int>> build_stock_blocks(
        const std::vector<Symbol>& symbols);

    // Determine percentile bounds for a given feature name
    std::pair<double, double> winsor_bounds(const std::string& name) const;
};

} // namespace trade
