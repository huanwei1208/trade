#include <gtest/gtest.h>
#include <Eigen/Dense>
#include <cmath>
#include <vector>

#include "trade/risk/covariance.h"
#include "trade/risk/var.h"
#include "trade/risk/drawdown.h"
#include "trade/risk/kelly.h"
#include "trade/risk/risk_monitor.h"

using namespace trade;

// =============================================================================
// CovarianceEstimator tests
// =============================================================================

TEST(CovarianceTest, EstimateBasicPSD) {
    // 3 assets, 50 observations of random-ish returns
    Eigen::MatrixXd returns(50, 3);
    for (int i = 0; i < 50; ++i) {
        returns(i, 0) = 0.001 * (i % 5 - 2);
        returns(i, 1) = 0.002 * (i % 3 - 1);
        returns(i, 2) = 0.0015 * (i % 7 - 3);
    }
    CovarianceEstimator est;
    auto cov = est.estimate(returns);
    EXPECT_EQ(cov.rows(), 3);
    EXPECT_EQ(cov.cols(), 3);
    // Should be symmetric
    EXPECT_NEAR(cov(0, 1), cov(1, 0), 1e-15);
    EXPECT_NEAR(cov(0, 2), cov(2, 0), 1e-15);
    // Diagonal should be positive (variances)
    EXPECT_GT(cov(0, 0), 0.0);
    EXPECT_GT(cov(1, 1), 0.0);
    EXPECT_GT(cov(2, 2), 0.0);
}

TEST(CovarianceTest, ShrinkageIntensityRange) {
    Eigen::MatrixXd returns(100, 3);
    for (int i = 0; i < 100; ++i) {
        returns(i, 0) = 0.001 * (i % 5 - 2);
        returns(i, 1) = 0.002 * (i % 3 - 1);
        returns(i, 2) = 0.0015 * (i % 7 - 3);
    }
    CovarianceEstimator est;
    est.estimate(returns);
    double delta = est.shrinkage_intensity();
    EXPECT_GE(delta, 0.0);
    EXPECT_LE(delta, 1.0);
}

TEST(CovarianceTest, ToCorrelation) {
    Eigen::MatrixXd cov(2, 2);
    cov << 0.04, 0.012,
           0.012, 0.09;
    auto corr = CovarianceEstimator::to_correlation(cov);
    // Diagonal should be 1.0
    EXPECT_NEAR(corr(0, 0), 1.0, 1e-10);
    EXPECT_NEAR(corr(1, 1), 1.0, 1e-10);
    // Off-diagonal: 0.012 / (0.2 * 0.3) = 0.2
    EXPECT_NEAR(corr(0, 1), 0.2, 1e-10);
    EXPECT_NEAR(corr(1, 0), 0.2, 1e-10);
}

TEST(CovarianceTest, AnnualisedVol) {
    Eigen::MatrixXd cov(2, 2);
    cov << 0.0004, 0.0,
           0.0, 0.0009;
    auto vol = CovarianceEstimator::annualised_vol(cov);
    // vol[0] = sqrt(0.0004) * sqrt(252) = 0.02 * 15.875 = 0.3175
    EXPECT_NEAR(vol(0), 0.02 * std::sqrt(252.0), 1e-4);
    // vol[1] = sqrt(0.0009) * sqrt(252) = 0.03 * 15.875 = 0.4762
    EXPECT_NEAR(vol(1), 0.03 * std::sqrt(252.0), 1e-4);
}

TEST(CovarianceTest, Decompose) {
    Eigen::MatrixXd cov(2, 2);
    cov << 2.0, 1.0,
           1.0, 2.0;
    auto decomp = CovarianceEstimator::decompose(cov);
    EXPECT_EQ(decomp.eigenvalues.size(), 2);
    // Eigenvalues of [[2,1],[1,2]] are 3 and 1
    EXPECT_NEAR(decomp.eigenvalues(0), 3.0, 1e-10);
    EXPECT_NEAR(decomp.eigenvalues(1), 1.0, 1e-10);
    EXPECT_NEAR(decomp.condition_number, 3.0, 1e-10);
}

// =============================================================================
// VaRCalculator tests
// =============================================================================

TEST(VaRTest, ParametricVaRSingleAsset) {
    // Single asset with daily vol = 0.02
    Eigen::VectorXd w(1);
    w << 1.0;
    Eigen::MatrixXd cov(1, 1);
    cov << 0.0004;  // daily variance = 0.02^2
    VaRCalculator calc;
    auto result = calc.parametric_var(w, cov);
    // VaR_99 = z_99 * sigma = 2.326 * 0.02 = 0.04652
    EXPECT_NEAR(result.var, 2.326 * 0.02, 0.01);
    EXPECT_EQ(result.method, "parametric");
    // CVaR should be larger than VaR
    EXPECT_GT(result.cvar, result.var);
}

TEST(VaRTest, ParametricVaRTwoAsset) {
    Eigen::VectorXd w(2);
    w << 0.6, 0.4;
    Eigen::MatrixXd cov(2, 2);
    cov << 0.04, 0.006,
           0.006, 0.09;
    VaRCalculator calc;
    auto result = calc.parametric_var(w, cov);
    double port_var = (w.transpose() * cov * w)(0, 0);
    double port_sigma = std::sqrt(port_var);
    double expected_var = 2.326 * port_sigma;
    EXPECT_NEAR(result.var, expected_var, 0.01);
}

TEST(VaRTest, HistoricalVaR) {
    Eigen::VectorXd w(2);
    w << 0.5, 0.5;
    // Generate historical returns
    Eigen::MatrixXd returns(500, 2);
    for (int i = 0; i < 500; ++i) {
        returns(i, 0) = 0.001 * ((i * 7 + 3) % 11 - 5);
        returns(i, 1) = 0.001 * ((i * 11 + 5) % 13 - 6);
    }
    VaRCalculator calc;
    auto result = calc.historical_var(w, returns);
    EXPECT_GT(result.var, 0.0);
    EXPECT_EQ(result.method, "historical");
    EXPECT_GE(result.cvar, result.var);
}

TEST(VaRTest, MarginalVarSumsToPortfolioVar) {
    Eigen::VectorXd w(3);
    w << 0.4, 0.3, 0.3;
    Eigen::MatrixXd cov(3, 3);
    cov << 0.04, 0.01, 0.005,
           0.01, 0.06, 0.008,
           0.005, 0.008, 0.03;
    VaRCalculator calc;
    auto comp = calc.component_var(w, cov);
    double port_sigma = std::sqrt((w.transpose() * cov * w)(0, 0));
    double comp_sum = comp.sum();
    // Component VaR should sum to z_alpha * port_sigma
    EXPECT_NEAR(comp_sum, 2.326 * port_sigma, 0.001);
}

TEST(VaRTest, CombinedVaRIsMax) {
    Eigen::VectorXd w(2);
    w << 0.6, 0.4;
    Eigen::MatrixXd cov(2, 2);
    cov << 0.04, 0.006,
           0.006, 0.09;
    Eigen::MatrixXd returns(500, 2);
    for (int i = 0; i < 500; ++i) {
        returns(i, 0) = 0.001 * ((i * 7 + 3) % 11 - 5);
        returns(i, 1) = 0.002 * ((i * 11 + 5) % 13 - 6);
    }
    VaRCalculator calc;
    auto combined = calc.compute(w, cov, returns);
    // Combined VaR should be max of the three layers
    double max_var = std::max({combined.parametric.var,
                                combined.historical.var,
                                combined.monte_carlo.var});
    EXPECT_NEAR(combined.var_1d_99, max_var, 1e-10);
}

// =============================================================================
// DrawdownController tests
// =============================================================================

TEST(DrawdownTest, ComputeDrawdownFromNAV) {
    std::vector<double> nav = {100, 105, 110, 100, 95, 98};
    double dd = DrawdownController::compute_drawdown(nav);
    // Peak = 110, current = 98, current_dd = (110-98)/110 = 0.10909
    // Or peak = 110, trough = 95, max_dd = (110-95)/110 = 0.13636
    // Accept either interpretation
    EXPECT_GT(dd, 0.05);
    EXPECT_LT(dd, 0.20);
}

TEST(DrawdownTest, ComputePeak) {
    std::vector<double> nav = {100, 105, 110, 100, 95, 98};
    double peak = DrawdownController::compute_peak(nav);
    EXPECT_DOUBLE_EQ(peak, 110.0);
}

TEST(DrawdownTest, ClassifyDrawdownLevels) {
    DrawdownController ctrl;
    EXPECT_EQ(ctrl.classify_drawdown(0.03), DrawdownController::DrawdownLevel::kNormal);
    EXPECT_EQ(ctrl.classify_drawdown(0.06), DrawdownController::DrawdownLevel::kLevel1);
    EXPECT_EQ(ctrl.classify_drawdown(0.09), DrawdownController::DrawdownLevel::kLevel2);
    EXPECT_EQ(ctrl.classify_drawdown(0.13), DrawdownController::DrawdownLevel::kLevel3);
    EXPECT_EQ(ctrl.classify_drawdown(0.16), DrawdownController::DrawdownLevel::kCapitalPreserve);
}

TEST(DrawdownTest, EvaluateLevel1) {
    // NAV drops 6% from peak
    std::vector<double> nav;
    for (int i = 0; i < 50; ++i) nav.push_back(100.0 + 0.1 * i);
    // Peak at 105, then drop to ~99
    nav.push_back(99.0);
    std::vector<double> returns(20, -0.001);
    DrawdownController ctrl;
    auto action = ctrl.evaluate(nav, returns);
    if (action.level >= DrawdownController::DrawdownLevel::kLevel1) {
        EXPECT_TRUE(action.freeze_high_beta_new);
        EXPECT_LT(action.target_exposure_multiplier, 1.0);
    }
}

TEST(DrawdownTest, VolScaling) {
    DrawdownController ctrl;
    // High vol returns
    std::vector<double> high_vol_returns;
    for (int i = 0; i < 30; ++i) {
        high_vol_returns.push_back(i % 2 == 0 ? 0.03 : -0.03);
    }
    auto scaling = ctrl.compute_vol_scaling(high_vol_returns);
    // Realized vol should be high => scale < 1.0
    EXPECT_LT(scaling.clamped_scale, 1.0);
    EXPECT_GE(scaling.clamped_scale, 0.5);  // floor
}

TEST(DrawdownTest, RealizedVol) {
    // Constant returns = zero vol
    std::vector<double> returns(20, 0.01);
    double vol = DrawdownController::realized_vol(returns, 20);
    EXPECT_NEAR(vol, 0.0, 1e-10);
}

TEST(DrawdownTest, AdjustWeightsLevel3) {
    DrawdownController ctrl;
    DrawdownController::DrawdownAction action;
    action.level = DrawdownController::DrawdownLevel::kLevel3;
    action.target_exposure_multiplier = 0.6;
    action.vol_scale = 0.8;
    action.effective_multiplier = 0.6;
    action.single_stock_cap = 0.05;
    action.capital_preservation_mode = false;

    Eigen::VectorXd weights(3);
    weights << 0.08, 0.06, 0.04;
    auto adjusted = ctrl.adjust_weights(weights, action);
    // All weights should be scaled down
    for (int i = 0; i < 3; ++i) {
        EXPECT_LE(adjusted(i), weights(i));
    }
}

// =============================================================================
// KellyCalculator tests
// =============================================================================

TEST(KellyTest, KellyFractionBasic) {
    // mu = 0.01, sigma = 0.05
    // full kelly = 0.01 / 0.05^2 = 4.0
    // quarter kelly = 0.25 * 4.0 = 1.0
    KellyCalculator calc;
    Eigen::VectorXd mu(1);
    mu << 0.01;
    Eigen::VectorXd sigma(1);
    sigma << 0.05;
    auto fracs = calc.kelly_fraction(mu, sigma);
    EXPECT_NEAR(fracs(0), 1.0, 0.01);
}

TEST(KellyTest, KellyFractionNegativeReturn) {
    KellyCalculator calc;
    Eigen::VectorXd mu(1);
    mu << -0.01;
    Eigen::VectorXd sigma(1);
    sigma << 0.05;
    auto fracs = calc.kelly_fraction(mu, sigma);
    // Negative expected return => Kelly suggests negative position
    EXPECT_LT(fracs(0), 0.0);
}

TEST(KellyTest, RiskParityWeights) {
    // 3 assets with different volatilities
    Eigen::VectorXd vols(3);
    vols << 0.10, 0.20, 0.30;
    // Equal risk budget
    Eigen::VectorXd rb(3);
    rb << 1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0;
    KellyCalculator calc;
    auto weights = calc.risk_parity_weights(rb, vols);
    // Risk parity: w_i ∝ rb_i / vol_i
    // Higher vol asset should get lower weight with equal budgets
    EXPECT_GT(weights(0), weights(1));
    EXPECT_GT(weights(1), weights(2));
    // Should sum to target_gross_exposure (default = 1.0)
    EXPECT_NEAR(weights.sum(), 1.0, 1e-6);
}

// =============================================================================
// RiskMonitor tests
// =============================================================================

TEST(RiskMonitorTest, ConfigDefaults) {
    RiskMonitor::Config cfg;
    EXPECT_GT(cfg.thresholds.yellow_var, 0.0);
    EXPECT_GT(cfg.thresholds.orange_var, cfg.thresholds.yellow_var);
    EXPECT_GT(cfg.thresholds.red_var, cfg.thresholds.orange_var);
}

TEST(RiskMonitorTest, AlertLevelProgression) {
    // Alert levels should progress: Green < Yellow < Orange < Red
    EXPECT_LT(static_cast<int>(AlertLevel::kGreen), static_cast<int>(AlertLevel::kYellow));
    EXPECT_LT(static_cast<int>(AlertLevel::kYellow), static_cast<int>(AlertLevel::kOrange));
    EXPECT_LT(static_cast<int>(AlertLevel::kOrange), static_cast<int>(AlertLevel::kRed));
}
