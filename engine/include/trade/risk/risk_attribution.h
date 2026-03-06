#pragma once

#include "trade/common/types.h"

#include <Eigen/Dense>
#include <string>
#include <unordered_map>
#include <vector>

namespace trade {

// ============================================================================
// RiskAttribution: variance decomposition and risk contribution analysis
// ============================================================================
//
// Decomposes total portfolio variance into:
//   - Factor risk:       w' * B * Sigma_f * B' * w
//   - Idiosyncratic risk: w' * D * w
//   where B = factor loading matrix (N x K), Sigma_f = factor covariance (K x K),
//         D = diagonal idiosyncratic variance matrix.
//
// Provides breakdowns by:
//   - Individual stock
//   - Industry (Shenwan Level-1)
//   - Style factor (momentum, value, size, volatility, quality, etc.)
//   - Liquidity bucket
//
// Reports top-5 risk contributors with marginal VaR and component VaR.
//
class RiskAttribution {
public:
    // -----------------------------------------------------------------------
    // Per-stock risk contribution
    // -----------------------------------------------------------------------
    struct StockContribution {
        Symbol symbol;
        double weight = 0.0;
        double marginal_var = 0.0;          // dVaR / dw_i
        double component_var = 0.0;         // w_i * marginal_VaR_i
        double component_var_pct = 0.0;     // component / total VaR (sums to 1)
        double factor_risk_contrib = 0.0;   // factor component
        double idio_risk_contrib = 0.0;     // idiosyncratic component
    };

    // -----------------------------------------------------------------------
    // Group-level risk (industry, style, liquidity bucket)
    // -----------------------------------------------------------------------
    struct GroupContribution {
        std::string group_name;
        double total_weight = 0.0;
        double component_var = 0.0;
        double component_var_pct = 0.0;
        int num_stocks = 0;
        std::vector<Symbol> members;
    };

    // -----------------------------------------------------------------------
    // Factor-level risk
    // -----------------------------------------------------------------------
    struct FactorContribution {
        std::string factor_name;
        double exposure = 0.0;             // portfolio factor loading
        double factor_var_contrib = 0.0;   // contribution to portfolio variance
        double factor_var_pct = 0.0;       // as fraction of total variance
    };

    // -----------------------------------------------------------------------
    // Complete decomposition result
    // -----------------------------------------------------------------------
    struct RiskDecomposition {
        // Total portfolio risk
        double total_variance = 0.0;        // w' * Sigma * w
        double total_vol = 0.0;             // sqrt(total_variance), annualised
        double total_var_99 = 0.0;          // 99% parametric VaR

        // Factor vs idiosyncratic split
        double factor_variance = 0.0;       // w' * B * Sigma_f * B' * w
        double idio_variance = 0.0;         // w' * D * w
        double factor_pct = 0.0;            // factor / total
        double idio_pct = 0.0;              // idio / total

        // Per-stock contributions (all stocks)
        std::vector<StockContribution> by_stock;

        // Top-5 risk contributors by |component_var|
        std::vector<StockContribution> top5_contributors;

        // Industry-level decomposition
        std::vector<GroupContribution> by_industry;

        // Style factor decomposition
        std::vector<FactorContribution> by_factor;

        // Liquidity bucket decomposition
        std::vector<GroupContribution> by_liquidity_bucket;

        // Diversification ratio: sum(w_i * sigma_i) / sigma_p
        double diversification_ratio = 0.0;

        // Effective number of bets: 1 / sum(component_var_pct_i^2)
        double effective_bets = 0.0;
    };

    // -----------------------------------------------------------------------
    // Liquidity bucket definitions
    // -----------------------------------------------------------------------
    struct LiquidityBucketConfig {
        // ADV thresholds for bucket classification (in notional)
        double high_liquidity_min = 1e8;    // > 100M yuan ADV
        double mid_liquidity_min = 3e7;     // > 30M yuan ADV
        // below mid = low liquidity
    };

    // -----------------------------------------------------------------------
    // Configuration
    // -----------------------------------------------------------------------
    struct Config {
        int top_n = 5;                      // top-N contributors
        LiquidityBucketConfig liquidity_buckets;
        double var_confidence = 0.99;       // for VaR computation
    };

    RiskAttribution() : config_{} {}
    explicit RiskAttribution(Config cfg) : config_(cfg) {}

    // -----------------------------------------------------------------------
    // Core interface
    // -----------------------------------------------------------------------

    // Full risk decomposition.
    //   weights:          (N,) portfolio weights
    //   covariance:       (N x N) full covariance matrix
    //   factor_loadings:  (N x K) factor loading matrix
    //   factor_cov:       (K x K) factor covariance matrix
    //   idio_var:         (N,) idiosyncratic variances (diagonal of D)
    //   symbols:          (N,) symbol identifiers
    //   industries:       (N,) industry classification per stock
    //   factor_names:     (K,) factor names
    //   adv:              (N,) 20-day ADV in notional (for liquidity buckets)
    RiskDecomposition decompose(
        const Eigen::VectorXd& weights,
        const Eigen::MatrixXd& covariance,
        const Eigen::MatrixXd& factor_loadings,
        const Eigen::MatrixXd& factor_cov,
        const Eigen::VectorXd& idio_var,
        const std::vector<Symbol>& symbols,
        const std::vector<SWIndustry>& industries,
        const std::vector<std::string>& factor_names,
        const Eigen::VectorXd& adv = {}) const;

    // -----------------------------------------------------------------------
    // Simplified interface (no factor model, uses full covariance only)
    // -----------------------------------------------------------------------
    RiskDecomposition decompose_simple(
        const Eigen::VectorXd& weights,
        const Eigen::MatrixXd& covariance,
        const std::vector<Symbol>& symbols,
        const std::vector<SWIndustry>& industries) const;

    // -----------------------------------------------------------------------
    // Component calculations (standalone)
    // -----------------------------------------------------------------------

    // Marginal VaR: (Sigma * w) / sigma_p * z_alpha
    static Eigen::VectorXd marginal_var(
        const Eigen::VectorXd& weights,
        const Eigen::MatrixXd& cov,
        double confidence = 0.99);

    // Component VaR: w_i * marginal_VaR_i
    static Eigen::VectorXd component_var(
        const Eigen::VectorXd& weights,
        const Eigen::MatrixXd& cov,
        double confidence = 0.99);

    // Diversification ratio
    static double diversification_ratio(
        const Eigen::VectorXd& weights,
        const Eigen::MatrixXd& cov);

    const Config& config() const { return config_; }

private:
    Config config_;

    // Classify stock into liquidity bucket name
    std::string liquidity_bucket_name(double adv) const;

    // Group contributions by a label vector
    static std::vector<GroupContribution> group_by(
        const Eigen::VectorXd& weights,
        const Eigen::VectorXd& component_vars,
        const std::vector<Symbol>& symbols,
        const std::vector<std::string>& group_labels);
};

} // namespace trade
