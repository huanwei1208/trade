#include "trade/risk/covariance.h"
#include "trade/model/bar.h"

#include <algorithm>
#include <cmath>
#include <unordered_map>
#include <unordered_set>

namespace trade {

// ---------------------------------------------------------------------------
// Ledoit-Wolf shrinkage covariance estimation
// ---------------------------------------------------------------------------
// Σ_shrunk = α * F + (1 - α) * S
// where S = sample covariance, F = shrinkage target (scaled identity: average
// variance on the diagonal), and α = optimal shrinkage intensity.
//
// The optimal intensity minimises E[||Σ_shrunk - Σ_true||²] under the Frobenius
// norm.  The closed-form expression from Ledoit & Wolf (2004) is:
//
//   α* = min(1, max(0, κ / T))
//
// where κ depends on the fourth moments of the centred returns.
// ---------------------------------------------------------------------------

Eigen::MatrixXd CovarianceEstimator::estimate(
    const Eigen::MatrixXd& returns_matrix) const {

    const int T = static_cast<int>(returns_matrix.rows());
    const int N = static_cast<int>(returns_matrix.cols());

    if (T < 2 || N == 0) {
        return Eigen::MatrixXd::Identity(std::max(N, 1), std::max(N, 1));
    }

    // Centre returns (subtract column means)
    Eigen::MatrixXd centred = returns_matrix;
    Eigen::VectorXd col_means = returns_matrix.colwise().mean();
    centred.rowwise() -= col_means.transpose();

    // Optionally apply exponential decay weights
    Eigen::VectorXd w = Eigen::VectorXd::Ones(T);
    if (config_.use_exponential_decay && config_.ewma_halflife > 0) {
        double lambda = std::log(2.0) / config_.ewma_halflife;
        for (int t = 0; t < T; ++t) {
            // Most recent observation is row T-1
            w(t) = std::exp(-lambda * (T - 1 - t));
        }
        double w_sum = w.sum();
        w /= w_sum;  // normalise so weights sum to 1

        // Apply sqrt(weight) to rows so that X'*X gives weighted covariance
        for (int t = 0; t < T; ++t) {
            centred.row(t) *= std::sqrt(w(t) * T);
        }
    }

    // Sample covariance: S = X' * X / (T - 1)
    Eigen::MatrixXd S = (centred.transpose() * centred) / static_cast<double>(T - 1);

    // Shrinkage target: scaled identity (average diagonal variance)
    Eigen::MatrixXd F = shrinkage_target(S);

    // Compute optimal shrinkage intensity
    double alpha = compute_shrinkage(centred, S);

    // Clamp to configured bounds
    alpha = std::max(config_.min_shrinkage, std::min(config_.max_shrinkage, alpha));
    last_shrinkage_ = alpha;

    // Shrunk covariance: Σ = α * F + (1 - α) * S
    Eigen::MatrixXd cov = alpha * F + (1.0 - alpha) * S;

    return cov;
}

// ---------------------------------------------------------------------------
// Compute Ledoit-Wolf optimal shrinkage intensity
// ---------------------------------------------------------------------------
// Following the Oracle Approximating Shrinkage (OAS) / Ledoit-Wolf (2004)
// formula.  We compute:
//
//   π_hat  = sum_{i,j} 1/T * sum_t (x_{ti}*x_{tj} - s_{ij})^2
//   rho_hat = similar sum but for the target
//   gamma_hat = ||S - F||_F^2
//   alpha* = max(0, min(1, (pi_hat - rho_hat) / (T * gamma_hat)))
//
double CovarianceEstimator::compute_shrinkage(
    const Eigen::MatrixXd& returns,
    const Eigen::MatrixXd& sample_cov) const {

    const int T = static_cast<int>(returns.rows());
    const int N = static_cast<int>(returns.cols());

    if (T <= 1 || N == 0) return 1.0;

    // Shrinkage target F
    double mu_trace = sample_cov.trace() / N;  // average variance
    Eigen::MatrixXd F = Eigen::MatrixXd::Identity(N, N) * mu_trace;

    // Compute pi_hat: asymptotic variance of the sample covariance entries
    // pi_hat = (1/T) * sum_{i,j} [ (1/T) * sum_t (y_{ti}*y_{tj} - s_{ij})^2 ]
    // where y = centred returns
    double pi_hat = 0.0;
    for (int i = 0; i < N; ++i) {
        for (int j = i; j < N; ++j) {
            double sum_sq = 0.0;
            for (int t = 0; t < T; ++t) {
                double cross = returns(t, i) * returns(t, j);
                // Use sample_cov scaled by (T-1)/T to match the unbiased vs biased convention
                double s_ij = sample_cov(i, j) * (T - 1.0) / T;
                double diff = cross - s_ij;
                sum_sq += diff * diff;
            }
            double pi_ij = sum_sq / T;
            if (i == j) {
                pi_hat += pi_ij;
            } else {
                pi_hat += 2.0 * pi_ij;  // symmetric
            }
        }
    }

    // Compute rho_hat: the sum of asymptotic covariances of the
    // shrinkage target entries with the sample covariance entries.
    // For scaled identity target F = mu*I:
    //   rho_hat = sum_i pi_{ii} * (mu / s_{ii})
    // This simplifies because off-diagonal F entries are zero.
    double rho_hat = 0.0;
    for (int i = 0; i < N; ++i) {
        double sum_sq = 0.0;
        for (int t = 0; t < T; ++t) {
            double cross = returns(t, i) * returns(t, i);
            double s_ii = sample_cov(i, i) * (T - 1.0) / T;
            double diff = cross - s_ii;
            sum_sq += diff * diff;
        }
        double pi_ii = sum_sq / T;
        // For diagonal target: the partial derivative w.r.t. s_{ii} times
        // the corresponding target entry
        if (sample_cov(i, i) > 1e-15) {
            rho_hat += pi_ii * (mu_trace / sample_cov(i, i));
        }
    }

    // Gamma: ||S - F||^2_F
    double gamma_hat = (sample_cov - F).squaredNorm();

    // Optimal intensity
    double kappa = (pi_hat - rho_hat) / T;
    double alpha = 0.0;
    if (gamma_hat > 1e-15) {
        alpha = kappa / gamma_hat;
    }

    // Clamp to [0, 1]
    alpha = std::max(0.0, std::min(1.0, alpha));

    return alpha;
}

// ---------------------------------------------------------------------------
// Shrinkage target: scaled identity matrix
// ---------------------------------------------------------------------------
Eigen::MatrixXd CovarianceEstimator::shrinkage_target(
    const Eigen::MatrixXd& sample_cov) {

    int N = static_cast<int>(sample_cov.rows());
    double avg_var = sample_cov.diagonal().mean();
    return Eigen::MatrixXd::Identity(N, N) * avg_var;
}

// ---------------------------------------------------------------------------
// Correlation matrix from covariance
// ---------------------------------------------------------------------------
Eigen::MatrixXd CovarianceEstimator::to_correlation(const Eigen::MatrixXd& cov) {
    int N = static_cast<int>(cov.rows());
    if (N == 0) return {};

    Eigen::VectorXd stdev = cov.diagonal().cwiseSqrt();
    Eigen::MatrixXd corr(N, N);

    for (int i = 0; i < N; ++i) {
        for (int j = 0; j < N; ++j) {
            if (stdev(i) > 1e-15 && stdev(j) > 1e-15) {
                corr(i, j) = cov(i, j) / (stdev(i) * stdev(j));
            } else {
                corr(i, j) = (i == j) ? 1.0 : 0.0;
            }
        }
    }

    return corr;
}

// ---------------------------------------------------------------------------
// Annualised volatility vector
// ---------------------------------------------------------------------------
Eigen::VectorXd CovarianceEstimator::annualised_vol(const Eigen::MatrixXd& cov) {
    return cov.diagonal().cwiseSqrt() * std::sqrt(252.0);
}

// ---------------------------------------------------------------------------
// Eigen decomposition: eigenvalues in descending order
// ---------------------------------------------------------------------------
CovarianceEstimator::EigenDecomp CovarianceEstimator::decompose(
    const Eigen::MatrixXd& cov) {

    EigenDecomp result;
    int N = static_cast<int>(cov.rows());
    if (N == 0) return result;

    // Self-adjoint eigen decomposition (returns eigenvalues in ascending order)
    Eigen::SelfAdjointEigenSolver<Eigen::MatrixXd> solver(cov);

    if (solver.info() != Eigen::Success) {
        // Fallback: return identity-like decomposition
        result.eigenvalues = Eigen::VectorXd::Ones(N);
        result.eigenvectors = Eigen::MatrixXd::Identity(N, N);
        result.condition_number = 1.0;
        return result;
    }

    Eigen::VectorXd evals = solver.eigenvalues();
    Eigen::MatrixXd evecs = solver.eigenvectors();

    // Reverse to descending order
    result.eigenvalues.resize(N);
    result.eigenvectors.resize(N, N);
    for (int i = 0; i < N; ++i) {
        result.eigenvalues(i) = evals(N - 1 - i);
        result.eigenvectors.col(i) = evecs.col(N - 1 - i);
    }

    // Condition number: ratio of largest to smallest positive eigenvalue
    double max_eval = result.eigenvalues(0);
    double min_eval = result.eigenvalues(N - 1);
    if (min_eval > 1e-15) {
        result.condition_number = max_eval / min_eval;
    } else {
        result.condition_number = std::numeric_limits<double>::infinity();
    }

    return result;
}

// ---------------------------------------------------------------------------
// Build returns matrix from BarSeries (close-to-close log returns)
// ---------------------------------------------------------------------------
Eigen::MatrixXd CovarianceEstimator::build_returns_matrix(
    const std::vector<BarSeries>& series,
    int lookback_days) {

    if (series.empty()) return {};

    int N = static_cast<int>(series.size());

    // Collect all unique dates across all series
    std::unordered_set<int64_t> all_dates_set;
    // Map from date (as epoch days) to row index
    for (const auto& s : series) {
        for (const auto& bar : s.bars) {
            all_dates_set.insert(bar.date.time_since_epoch().count());
        }
    }

    // Sort dates ascending
    std::vector<int64_t> all_dates(all_dates_set.begin(), all_dates_set.end());
    std::sort(all_dates.begin(), all_dates.end());

    // Trim to the most recent lookback_days
    if (static_cast<int>(all_dates.size()) > lookback_days + 1) {
        // We need lookback_days returns, which requires lookback_days+1 prices
        all_dates.erase(all_dates.begin(),
                        all_dates.end() - (lookback_days + 1));
    }

    int T_prices = static_cast<int>(all_dates.size());
    if (T_prices < 2) return {};

    // Map from date to sequential index
    std::unordered_map<int64_t, int> date_to_idx;
    for (int i = 0; i < T_prices; ++i) {
        date_to_idx[all_dates[i]] = i;
    }

    // Build price matrix (T_prices x N), fill with NaN as placeholder
    Eigen::MatrixXd prices = Eigen::MatrixXd::Constant(T_prices, N,
                                std::numeric_limits<double>::quiet_NaN());

    for (int j = 0; j < N; ++j) {
        for (const auto& bar : series[j].bars) {
            int64_t d = bar.date.time_since_epoch().count();
            auto it = date_to_idx.find(d);
            if (it != date_to_idx.end() && bar.close > 0.0) {
                prices(it->second, j) = bar.close;
            }
        }
    }

    // Compute log returns: r_t = ln(P_t / P_{t-1})
    int T_returns = T_prices - 1;
    Eigen::MatrixXd returns = Eigen::MatrixXd::Zero(T_returns, N);

    for (int t = 1; t < T_prices; ++t) {
        for (int j = 0; j < N; ++j) {
            double p_prev = prices(t - 1, j);
            double p_curr = prices(t, j);
            if (std::isfinite(p_prev) && std::isfinite(p_curr) &&
                p_prev > 0.0 && p_curr > 0.0) {
                returns(t - 1, j) = std::log(p_curr / p_prev);
            }
            // else leave as 0.0 (missing data => no return)
        }
    }

    return returns;
}

} // namespace trade
