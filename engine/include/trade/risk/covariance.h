#pragma once

#include "trade/common/types.h"
#include "trade/model/bar.h"

#include <Eigen/Dense>
#include <cmath>
#include <vector>

namespace trade {

// ============================================================================
// CovarianceEstimator: Ledoit-Wolf shrinkage covariance estimation
// ============================================================================
// Estimates the covariance matrix from daily returns using the Ledoit-Wolf
// shrinkage estimator.  The shrinkage target is a scaled identity matrix
// (constant correlation model) which stabilises the eigenvalue spectrum and
// makes the estimate invertible even when N ~ T.
//
// Refresh schedule: daily, using the trailing 250 trading days of returns.
//
// Reference:
//   Ledoit & Wolf (2004) "A well-conditioned estimator for large-dimensional
//   covariance matrices", Journal of Multivariate Analysis.
//
class CovarianceEstimator {
public:
    struct Config {
        int lookback_days = 250;        // number of trailing return days
        double min_shrinkage = 0.0;     // floor on shrinkage intensity
        double max_shrinkage = 1.0;     // cap on shrinkage intensity
        bool use_exponential_decay = false;
        int ewma_halflife = 60;         // halflife in days if exponential decay
    };

    CovarianceEstimator() : config_{} {}
    explicit CovarianceEstimator(Config cfg) : config_(cfg) {}

    // -----------------------------------------------------------------------
    // Core interface
    // -----------------------------------------------------------------------

    // Estimate the shrinkage covariance matrix from a returns matrix.
    //   returns_matrix: (T x N) -- T observations of N asset returns
    // Returns: (N x N) positive semi-definite covariance matrix.
    Eigen::MatrixXd estimate(const Eigen::MatrixXd& returns_matrix) const;

    // Returns the optimal shrinkage intensity from the last call to estimate().
    // Range [0, 1]: 0 = sample covariance, 1 = shrinkage target only.
    double shrinkage_intensity() const { return last_shrinkage_; }

    // -----------------------------------------------------------------------
    // Decomposition helpers
    // -----------------------------------------------------------------------

    // Correlation matrix from covariance
    static Eigen::MatrixXd to_correlation(const Eigen::MatrixXd& cov);

    // Annualised volatility vector (diagonal sqrt * sqrt(252))
    static Eigen::VectorXd annualised_vol(const Eigen::MatrixXd& cov);

    // Eigen decomposition: eigenvalues in descending order
    struct EigenDecomp {
        Eigen::VectorXd eigenvalues;    // (N,) descending
        Eigen::MatrixXd eigenvectors;   // (N x N) columns are eigenvectors
        double condition_number = 0.0;
    };
    static EigenDecomp decompose(const Eigen::MatrixXd& cov);

    // -----------------------------------------------------------------------
    // Utilities
    // -----------------------------------------------------------------------

    // Build a returns matrix from BarSeries vector (close-to-close log returns).
    // Rows are dates (oldest first), columns are assets.
    // Missing data is filled with 0.0 (no return).
    static Eigen::MatrixXd build_returns_matrix(
        const std::vector<BarSeries>& series,
        int lookback_days = 250);

    const Config& config() const { return config_; }

private:
    Config config_;
    mutable double last_shrinkage_ = 0.0;

    // Ledoit-Wolf optimal shrinkage intensity calculation
    double compute_shrinkage(
        const Eigen::MatrixXd& returns,
        const Eigen::MatrixXd& sample_cov) const;

    // Shrinkage target: scaled identity (avg variance on diagonal)
    static Eigen::MatrixXd shrinkage_target(const Eigen::MatrixXd& sample_cov);
};

} // namespace trade
