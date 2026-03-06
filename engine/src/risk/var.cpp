#include "trade/risk/var.h"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <random>
#include <vector>

namespace trade {

// ---------------------------------------------------------------------------
// Rational approximation for the inverse normal CDF (Beasley-Springer-Moro)
// ---------------------------------------------------------------------------
// Accurate to ~1e-9 for p in (1e-8, 1-1e-8).
double VaRCalculator::norm_quantile(double p) {
    if (p <= 0.0) return -1e10;
    if (p >= 1.0) return 1e10;
    if (std::abs(p - 0.5) < 1e-15) return 0.0;

    // Rational approximation constants (Peter Acklam's algorithm)
    static const double a[] = {
        -3.969683028665376e+01,  2.209460984245205e+02,
        -2.759285104469687e+02,  1.383577518672690e+02,
        -3.066479806614716e+01,  2.506628277459239e+00
    };
    static const double b[] = {
        -5.447609879822406e+01,  1.615858368580409e+02,
        -1.556989798598866e+02,  6.680131188771972e+01,
        -1.328068155288572e+01
    };
    static const double c[] = {
        -7.784894002430293e-03, -3.223964580411365e-01,
        -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00,  2.938163982698783e+00
    };
    static const double d[] = {
         7.784695709041462e-03,  3.224671290700398e-01,
         2.445134137142996e+00,  3.754408661907416e+00
    };

    static const double p_low  = 0.02425;
    static const double p_high = 1.0 - p_low;

    double q, r;

    if (p < p_low) {
        // Left tail
        q = std::sqrt(-2.0 * std::log(p));
        return (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) /
               ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1.0);
    } else if (p <= p_high) {
        // Central region
        q = p - 0.5;
        r = q * q;
        return (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5]) * q /
               (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1.0);
    } else {
        // Right tail
        q = std::sqrt(-2.0 * std::log(1.0 - p));
        return -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) /
                ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1.0);
    }
}

// ---------------------------------------------------------------------------
// Standard normal PDF
// ---------------------------------------------------------------------------
double VaRCalculator::norm_pdf(double x) {
    static const double inv_sqrt_2pi = 1.0 / std::sqrt(2.0 * M_PI);
    return inv_sqrt_2pi * std::exp(-0.5 * x * x);
}

// ---------------------------------------------------------------------------
// z-score for the configured confidence level
// ---------------------------------------------------------------------------
double VaRCalculator::z_alpha() const {
    return norm_quantile(config_.confidence_level);
}

// ---------------------------------------------------------------------------
// Layer 1: Parametric VaR / CVaR
// ---------------------------------------------------------------------------
//   VaR_alpha  = -(mu_p) + z_alpha * sigma_p
//   CVaR_alpha = -(mu_p) + phi(z_alpha) / (1 - alpha) * sigma_p
//
// Convention: VaR is reported as a positive number representing a loss.
VaRCalculator::VaRResult VaRCalculator::parametric_var(
    const Eigen::VectorXd& weights,
    const Eigen::MatrixXd& cov,
    const Eigen::VectorXd& mu) const {

    VaRResult result;
    result.method = "parametric";
    result.confidence = config_.confidence_level;

    int N = static_cast<int>(weights.size());
    if (N == 0 || cov.rows() != N) return result;

    // Portfolio mean return
    double mu_p = 0.0;
    if (mu.size() == N) {
        mu_p = weights.dot(mu);
    }

    // Portfolio variance and standard deviation
    double port_var = (weights.transpose() * cov * weights).value();
    if (port_var < 0.0) port_var = 0.0;
    double sigma_p = std::sqrt(port_var);

    // Scale for multi-day horizon (square root of time)
    double horizon_scale = std::sqrt(static_cast<double>(config_.horizon_days));
    double z = z_alpha();

    // VaR (positive = loss): -mu_p * h + z * sigma_p * sqrt(h)
    result.var = -mu_p * config_.horizon_days + z * sigma_p * horizon_scale;

    // CVaR (expected shortfall): -mu_p * h + phi(z)/(1-alpha) * sigma_p * sqrt(h)
    double alpha = config_.confidence_level;
    double phi_z = norm_pdf(z);
    result.cvar = -mu_p * config_.horizon_days +
                  (phi_z / (1.0 - alpha)) * sigma_p * horizon_scale;

    // Ensure non-negative
    result.var = std::max(0.0, result.var);
    result.cvar = std::max(result.var, result.cvar);

    return result;
}

// ---------------------------------------------------------------------------
// Layer 2: Historical simulation VaR / CVaR
// ---------------------------------------------------------------------------
// Full repricing: compute portfolio P&L from historical returns and sort.
VaRCalculator::VaRResult VaRCalculator::historical_var(
    const Eigen::VectorXd& weights,
    const Eigen::MatrixXd& returns_matrix) const {

    VaRResult result;
    result.method = "historical";
    result.confidence = config_.confidence_level;

    int N = static_cast<int>(weights.size());
    int T = static_cast<int>(returns_matrix.rows());
    if (N == 0 || T == 0 || returns_matrix.cols() != N) return result;

    // Use the most recent 'historical_window' days (or all available)
    int window = std::min(T, config_.historical_window);
    int start_row = T - window;

    // Compute portfolio returns for each historical day
    std::vector<double> port_returns(window);
    for (int t = 0; t < window; ++t) {
        double pr = 0.0;
        for (int i = 0; i < N; ++i) {
            pr += weights(i) * returns_matrix(start_row + t, i);
        }
        port_returns[t] = pr;
    }

    // For multi-day horizon, aggregate overlapping windows
    int horizon = config_.horizon_days;
    std::vector<double> horizon_returns;
    if (horizon > 1 && window >= horizon) {
        horizon_returns.reserve(window - horizon + 1);
        for (int t = 0; t <= window - horizon; ++t) {
            double cumul = 0.0;
            for (int h = 0; h < horizon; ++h) {
                cumul += port_returns[t + h];
            }
            horizon_returns.push_back(cumul);
        }
    } else {
        horizon_returns = port_returns;
    }

    // Sort returns ascending (losses first)
    std::sort(horizon_returns.begin(), horizon_returns.end());

    int n_returns = static_cast<int>(horizon_returns.size());
    if (n_returns == 0) return result;

    // VaR: the (1-alpha) percentile of portfolio return distribution (negated)
    // For 99% VaR, we look at the 1st percentile
    double idx_d = (1.0 - config_.confidence_level) * n_returns;
    int idx = std::max(0, std::min(n_returns - 1, static_cast<int>(std::floor(idx_d))));
    result.var = -horizon_returns[idx];

    // CVaR: average of returns below (and including) the VaR threshold
    int count = idx + 1;
    double sum_tail = 0.0;
    for (int i = 0; i < count; ++i) {
        sum_tail += horizon_returns[i];
    }
    result.cvar = -(sum_tail / count);

    // Ensure non-negative
    result.var = std::max(0.0, result.var);
    result.cvar = std::max(result.var, result.cvar);

    return result;
}

// ---------------------------------------------------------------------------
// Layer 3: Monte Carlo stress VaR
// ---------------------------------------------------------------------------
// Generate scenarios from multivariate Student-t distribution (fat tails).
// If position and ADV data are provided, apply a liquidity haircut.
VaRCalculator::VaRResult VaRCalculator::monte_carlo_var(
    const Eigen::VectorXd& weights,
    const Eigen::MatrixXd& cov,
    const Eigen::VectorXd& mu,
    const Eigen::VectorXd& adv,
    const Eigen::VectorXd& positions) const {

    VaRResult result;
    result.method = "montecarlo";
    result.confidence = config_.confidence_level;

    int N = static_cast<int>(weights.size());
    if (N == 0 || cov.rows() != N) return result;

    // Cholesky decomposition for correlated normal generation: Sigma = L * L'
    Eigen::LLT<Eigen::MatrixXd> llt(cov);
    if (llt.info() != Eigen::Success) {
        // If Cholesky fails, add small ridge for numerical stability
        Eigen::MatrixXd cov_reg = cov;
        double ridge = 1e-8 * cov.diagonal().mean();
        cov_reg.diagonal().array() += ridge;
        llt.compute(cov_reg);
        if (llt.info() != Eigen::Success) {
            // Still fails: fall back to parametric
            return parametric_var(weights, cov, mu);
        }
    }
    Eigen::MatrixXd L = llt.matrixL();

    // Expected returns
    Eigen::VectorXd expected = Eigen::VectorXd::Zero(N);
    if (mu.size() == N) {
        expected = mu;
    }

    // Liquidity haircut: if a position is large relative to ADV, apply
    // additional slippage cost proportional to position / ADV ratio.
    Eigen::VectorXd liq_haircut = Eigen::VectorXd::Zero(N);
    bool have_liquidity = (adv.size() == N && positions.size() == N);
    if (have_liquidity) {
        for (int i = 0; i < N; ++i) {
            if (adv(i) > 0.0) {
                // Days to liquidate this position
                double days_to_liq = std::abs(positions(i)) / adv(i);
                // Haircut: 50 bps per day of liquidation
                liq_haircut(i) = days_to_liq * 0.005;
            }
        }
    }

    // Random number generation
    std::mt19937 rng(config_.random_seed);
    std::normal_distribution<double> normal_dist(0.0, 1.0);
    std::chi_squared_distribution<double> chi2_dist(config_.mc_t_df);

    double horizon_scale = std::sqrt(static_cast<double>(config_.horizon_days));
    int n_sims = config_.mc_simulations;

    // Generate portfolio returns for each scenario
    std::vector<double> sim_returns(n_sims);
    Eigen::VectorXd z(N);

    for (int s = 0; s < n_sims; ++s) {
        // Generate standard normals
        for (int i = 0; i < N; ++i) {
            z(i) = normal_dist(rng);
        }

        // Generate chi-squared for Student-t scaling
        double chi2_val = chi2_dist(rng);
        double t_scale = std::sqrt(config_.mc_t_df / chi2_val);

        // Correlated fat-tailed returns: r = mu*h + L * z * t_scale * sqrt(h)
        Eigen::VectorXd scenario = expected * config_.horizon_days
                                   + L * z * t_scale * horizon_scale;

        // Apply liquidity haircut
        if (have_liquidity) {
            for (int i = 0; i < N; ++i) {
                if (scenario(i) < 0.0) {
                    // Losses amplified by illiquidity
                    scenario(i) -= liq_haircut(i) * std::abs(scenario(i));
                }
            }
        }

        // Portfolio return
        sim_returns[s] = weights.dot(scenario);
    }

    // Sort ascending
    std::sort(sim_returns.begin(), sim_returns.end());

    // VaR: (1-alpha) percentile
    double idx_d = (1.0 - config_.confidence_level) * n_sims;
    int idx = std::max(0, std::min(n_sims - 1, static_cast<int>(std::floor(idx_d))));
    result.var = -sim_returns[idx];

    // CVaR: mean of tail
    int count = idx + 1;
    double sum_tail = 0.0;
    for (int i = 0; i < count; ++i) {
        sum_tail += sim_returns[i];
    }
    result.cvar = -(sum_tail / count);

    // Ensure non-negative
    result.var = std::max(0.0, result.var);
    result.cvar = std::max(result.var, result.cvar);

    return result;
}

// ---------------------------------------------------------------------------
// Combined: production VaR = max across all three layers
// ---------------------------------------------------------------------------
VaRCalculator::CombinedVaR VaRCalculator::compute(
    const Eigen::VectorXd& weights,
    const Eigen::MatrixXd& cov,
    const Eigen::MatrixXd& returns_matrix,
    const Eigen::VectorXd& mu,
    const Eigen::VectorXd& adv,
    const Eigen::VectorXd& positions) const {

    CombinedVaR result;

    // Layer 1: Parametric
    result.parametric = parametric_var(weights, cov, mu);

    // Layer 2: Historical simulation
    result.historical = historical_var(weights, returns_matrix);

    // Layer 3: Monte Carlo
    result.monte_carlo = monte_carlo_var(weights, cov, mu, adv, positions);

    // Production metric: max across all layers
    result.var_1d_99 = std::max({result.parametric.var,
                                  result.historical.var,
                                  result.monte_carlo.var});

    result.cvar_1d_99 = std::max({result.parametric.cvar,
                                   result.historical.cvar,
                                   result.monte_carlo.cvar});

    return result;
}

// ---------------------------------------------------------------------------
// Marginal VaR: dVaR / dw_i = (Sigma * w)_i / sigma_p * z_alpha
// ---------------------------------------------------------------------------
Eigen::VectorXd VaRCalculator::marginal_var(
    const Eigen::VectorXd& weights,
    const Eigen::MatrixXd& cov) const {

    int N = static_cast<int>(weights.size());
    if (N == 0 || cov.rows() != N) return Eigen::VectorXd::Zero(N);

    double port_var = (weights.transpose() * cov * weights).value();
    double sigma_p = std::sqrt(std::max(0.0, port_var));
    if (sigma_p <= 1e-15) return Eigen::VectorXd::Zero(N);

    double z = z_alpha();
    Eigen::VectorXd sigma_w = cov * weights;

    return (sigma_w / sigma_p) * z;
}

// ---------------------------------------------------------------------------
// Component VaR: w_i * marginal_VaR_i  (sums to portfolio VaR)
// ---------------------------------------------------------------------------
Eigen::VectorXd VaRCalculator::component_var(
    const Eigen::VectorXd& weights,
    const Eigen::MatrixXd& cov) const {

    Eigen::VectorXd m_var = marginal_var(weights, cov);
    return weights.array() * m_var.array();
}

} // namespace trade
