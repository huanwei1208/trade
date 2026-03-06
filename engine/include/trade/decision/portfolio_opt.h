#pragma once

#include "trade/common/types.h"
#include "trade/common/config.h"
#include "trade/decision/signal.h"

#include <Eigen/Dense>
#include <string>
#include <unordered_map>
#include <vector>

namespace trade {

// ============================================================================
// PortfolioOptimizer: constrained mean-variance portfolio optimisation
// ============================================================================
//
// Objective:
//   maximise  E[alpha]  -  transaction_cost  -  lambda * risk_penalty
//
// where:
//   E[alpha]         = w' * alpha_vector
//   transaction_cost = sum_i |w_i - w_i_current| * cost_i
//   risk_penalty     = w' * Sigma * w    (portfolio variance)
//
// Constraints:
//   1. VaR/CVaR limit:     VaR_99_1d <= budget
//   2. Portfolio Beta:     beta_min <= w' * beta <= beta_max   ([0.6, 1.2])
//   3. Single-stock cap:   |w_i| <= max_single_weight
//   4. Industry cap:       sum_j(w_j) <= max_industry for each industry
//   5. Top-3 concentration: sum of top-3 weights <= 22%
//   6. Cash floor:         1 - sum(w_i) >= cash_min
//   7. Turnover cap:       sum_i |w_i - w_i_current| <= max_turnover
//   8. Style factor exposure: |z_k| <= 1.0 per factor k
//
// Input:
//   - Candidate signals: top K = 15-25 stocks by alpha adjusted for cost.
//   - Current portfolio weights.
//   - Covariance matrix (from CovarianceEstimator).
//   - Risk / constraint configuration.
//
// Output:
//   - Target weights + trade list (buy/sell to reach target).
//
class PortfolioOptimizer {
public:
    // -----------------------------------------------------------------------
    // Constraint specification
    // -----------------------------------------------------------------------
    struct Constraints {
        // VaR / CVaR budget
        double max_var_99_1d = 0.03;            // max 3% daily VaR at 99%

        // Beta bounds
        double beta_min = 0.6;
        double beta_max = 1.2;

        // Concentration limits
        double max_single_weight = 0.10;        // hard cap per stock
        double max_industry_weight = 0.35;      // hard cap per SW industry
        double max_top3_weight = 0.22;          // top-3 combined

        // Cash
        double cash_floor = 0.10;               // minimum cash fraction

        // Turnover
        double max_turnover = 0.30;             // max one-way turnover per rebalance

        // Style factor exposure
        double max_factor_z = 1.0;              // |z| <= 1.0 per factor

        // Number of positions
        int max_positions = 25;
        int min_positions = 15;

        // Risk aversion
        double risk_aversion = 1.0;             // lambda in objective
    };

    // -----------------------------------------------------------------------
    // Candidate signal (pre-screened by alpha-adjusted-for-cost)
    // -----------------------------------------------------------------------
    struct Candidate {
        Symbol symbol;
        double alpha = 0.0;                     // expected alpha (from Signal)
        double confidence = 0.0;                // signal confidence
        double estimated_cost = 0.0;            // one-way transaction cost in bps
        double beta = 1.0;                      // stock beta to benchmark
        double adv_20d = 0.0;                   // 20-day average daily volume (yuan)
        SWIndustry industry = SWIndustry::kUnknown;
    };

    // -----------------------------------------------------------------------
    // Trade instruction produced by the optimizer
    // -----------------------------------------------------------------------
    struct TradeInstruction {
        Symbol symbol;
        Side side = Side::kBuy;
        double target_weight = 0.0;             // desired portfolio weight
        double current_weight = 0.0;            // weight before trade
        double delta_weight = 0.0;              // target - current
        double estimated_cost_bps = 0.0;        // round-trip cost estimate
        std::string reason;                     // why this trade is proposed
    };

    // -----------------------------------------------------------------------
    // Optimisation result
    // -----------------------------------------------------------------------
    struct OptimizationResult {
        // Target portfolio
        std::vector<Symbol> symbols;
        Eigen::VectorXd target_weights;          // (K,) optimised weights

        // Trade list
        std::vector<TradeInstruction> trades;    // only non-trivial deltas

        // Expected metrics
        double expected_alpha = 0.0;             // w' * alpha
        double expected_cost = 0.0;              // total transaction cost (bps)
        double expected_risk = 0.0;              // sqrt(w' * Sigma * w), annualised

        // Risk metrics at target
        struct RiskMetrics {
            double portfolio_var_99_1d = 0.0;
            double portfolio_cvar_99_1d = 0.0;
            double portfolio_beta = 0.0;
            double gross_exposure = 0.0;
            double net_exposure = 0.0;
            double cash_weight = 0.0;
            double turnover = 0.0;
            double max_single_weight = 0.0;
            double max_industry_weight = 0.0;
            double top3_weight = 0.0;
            int num_positions = 0;
        } risk_metrics;

        // Solver diagnostics
        bool converged = false;
        int iterations = 0;
        double objective_value = 0.0;

        // Constraint violations (empty if all satisfied)
        std::vector<std::string> constraint_violations;
    };

    PortfolioOptimizer();
    explicit PortfolioOptimizer(Constraints constraints);

    // -----------------------------------------------------------------------
    // Main optimisation interface
    // -----------------------------------------------------------------------
    //   candidates:       top-K candidate signals (pre-sorted by alpha - cost)
    //   current_weights:  current portfolio weights keyed by symbol
    //   covariance:       (K x K) covariance matrix of candidate returns
    //   factor_loadings:  (K x F) style factor loadings (optional)
    //   betas:            (K,) per-stock betas (optional, extracted from candidates)
    // Returns: OptimizationResult with target weights and trade list.
    OptimizationResult optimize(
        const std::vector<Candidate>& candidates,
        const std::unordered_map<Symbol, double>& current_weights,
        const Eigen::MatrixXd& covariance,
        const Eigen::MatrixXd& factor_loadings = {},
        const Eigen::VectorXd& betas = {}) const;

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    // Select top-K candidates by alpha adjusted for cost.
    //   alpha_cost_multiple: alpha must exceed cost * this to qualify.
    static std::vector<Candidate> select_candidates(
        const std::vector<Signal>& signals,
        const std::unordered_map<Symbol, double>& cost_estimates,
        const std::unordered_map<Symbol, double>& betas,
        const std::unordered_map<Symbol, SWIndustry>& industries,
        const std::unordered_map<Symbol, double>& adv_20d,
        double alpha_cost_multiple = 1.5,
        int max_k = 25);

    // Generate trade instructions from current -> target weights.
    static std::vector<TradeInstruction> generate_trades(
        const std::vector<Symbol>& symbols,
        const Eigen::VectorXd& target_weights,
        const std::unordered_map<Symbol, double>& current_weights,
        double rebalance_threshold = 0.01);

    const Constraints& constraints() const { return constraints_; }
    void set_constraints(const Constraints& c) { constraints_ = c; }

private:
    Constraints constraints_;

    // Internal solver: quadratic programming with linear constraints
    // Uses iterative clamp-and-rescale when a full QP solver is unavailable.
    OptimizationResult solve_qp(
        const Eigen::VectorXd& alpha_vec,
        const Eigen::VectorXd& cost_vec,
        const Eigen::MatrixXd& covariance,
        const Eigen::VectorXd& current_w,
        const Eigen::MatrixXd& factor_loadings,
        const Eigen::VectorXd& betas,
        const std::vector<SWIndustry>& industries) const;

    // Check all constraints and return violation descriptions
    std::vector<std::string> check_constraints(
        const Eigen::VectorXd& weights,
        const Eigen::VectorXd& betas,
        const std::vector<SWIndustry>& industries,
        const Eigen::MatrixXd& covariance,
        const Eigen::MatrixXd& factor_loadings,
        double turnover) const;
};

} // namespace trade
