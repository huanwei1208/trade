#include <gtest/gtest.h>
#include <Eigen/Dense>
#include <cmath>
#include <numeric>
#include <vector>

#include "trade/stats/correlation.h"
#include "trade/stats/descriptive.h"

using namespace trade;

// =============================================================================
// CorrelationAnalysis tests
// =============================================================================

TEST(CorrelationTest, ICPerfectPositive) {
    Eigen::VectorXd factor(5);
    factor << 1, 2, 3, 4, 5;
    Eigen::VectorXd returns(5);
    returns << 0.01, 0.02, 0.03, 0.04, 0.05;
    double ic = CorrelationAnalysis::information_coefficient(factor, returns);
    EXPECT_NEAR(ic, 1.0, 1e-10);
}

TEST(CorrelationTest, ICPerfectNegative) {
    Eigen::VectorXd factor(5);
    factor << 1, 2, 3, 4, 5;
    Eigen::VectorXd returns(5);
    returns << 0.05, 0.04, 0.03, 0.02, 0.01;
    double ic = CorrelationAnalysis::information_coefficient(factor, returns);
    EXPECT_NEAR(ic, -1.0, 1e-10);
}

TEST(CorrelationTest, ICZeroCorrelation) {
    Eigen::VectorXd factor(4);
    factor << 1, -1, 1, -1;
    Eigen::VectorXd returns(4);
    returns << 1, 1, -1, -1;
    double ic = CorrelationAnalysis::information_coefficient(factor, returns);
    EXPECT_NEAR(ic, 0.0, 1e-10);
}

TEST(CorrelationTest, RankICPerfect) {
    Eigen::VectorXd factor(5);
    factor << 10, 20, 30, 40, 50;
    Eigen::VectorXd returns(5);
    returns << 0.01, 0.02, 0.03, 0.04, 0.05;
    double ric = CorrelationAnalysis::rank_ic(factor, returns);
    EXPECT_NEAR(ric, 1.0, 1e-6);
}

TEST(CorrelationTest, RankICNonLinear) {
    // Monotonic non-linear => rank IC = 1
    Eigen::VectorXd factor(5);
    factor << 1, 2, 3, 4, 5;
    Eigen::VectorXd returns(5);
    returns << 1, 4, 9, 16, 25;
    double ric = CorrelationAnalysis::rank_ic(factor, returns);
    EXPECT_NEAR(ric, 1.0, 1e-6);
}

TEST(CorrelationTest, ToRanksOrdering) {
    Eigen::VectorXd v(4);
    v << 30, 10, 40, 20;
    auto ranks = CorrelationAnalysis::to_ranks(v);
    EXPECT_LT(ranks(1), ranks(3));  // 10 < 20
    EXPECT_LT(ranks(3), ranks(0));  // 20 < 30
    EXPECT_LT(ranks(0), ranks(2));  // 30 < 40
}

TEST(CorrelationTest, ForwardReturns) {
    Eigen::VectorXd prices(5);
    prices << 100, 102, 105, 103, 108;
    auto fwd = CorrelationAnalysis::forward_returns(prices, 1);
    EXPECT_NEAR(fwd(0), 0.02, 1e-10);
    EXPECT_NEAR(fwd(1), 105.0 / 102.0 - 1.0, 1e-10);
    EXPECT_EQ(fwd.size(), 4);
}

TEST(CorrelationTest, ForwardReturnsMultiHorizon) {
    Eigen::VectorXd prices(6);
    prices << 100, 102, 105, 103, 108, 110;
    auto fwd2 = CorrelationAnalysis::forward_returns(prices, 2);
    EXPECT_NEAR(fwd2(0), 0.05, 1e-10);
    EXPECT_EQ(fwd2.size(), 4);
}

TEST(CorrelationTest, ICIR) {
    Eigen::VectorXd ic_series(10);
    for (int i = 0; i < 10; ++i) ic_series(i) = 0.03 + 0.001 * i;
    double icir = CorrelationAnalysis::ic_ir(ic_series);
    EXPECT_GT(icir, 1.0);
}

TEST(CorrelationTest, CrossFactorCorrelation) {
    Eigen::MatrixXd factors(5, 2);
    factors << 1, 2,
               2, 4,
               3, 6,
               4, 8,
               5, 10;
    auto corr = CorrelationAnalysis::cross_factor_correlation(factors);
    EXPECT_EQ(corr.rows(), 2);
    EXPECT_EQ(corr.cols(), 2);
    EXPECT_NEAR(corr(0, 0), 1.0, 1e-10);
    EXPECT_NEAR(corr(1, 1), 1.0, 1e-10);
    EXPECT_NEAR(corr(0, 1), 1.0, 1e-10);
}

TEST(CorrelationTest, TtestPvalueSignificant) {
    Eigen::VectorXd sample(20);
    for (int i = 0; i < 20; ++i) sample(i) = 0.05 + 0.001 * i;
    double pval = CorrelationAnalysis::ttest_pvalue(sample);
    EXPECT_LT(pval, 0.05);
}

TEST(CorrelationTest, TtestPvalueNotSignificant) {
    Eigen::VectorXd sample(20);
    for (int i = 0; i < 20; ++i) sample(i) = (i % 2 == 0) ? 0.01 : -0.01;
    double pval = CorrelationAnalysis::ttest_pvalue(sample);
    EXPECT_GT(pval, 0.5);
}

// =============================================================================
// ICDecayProfile tests
// =============================================================================

TEST(ICDecayTest, PeakHorizon) {
    ICDecayProfile profile;
    profile.factor_name = "test";
    ICResult r1; r1.horizon = 1; r1.rank_ic = 0.02;
    ICResult r2; r2.horizon = 5; r2.rank_ic = 0.04;
    ICResult r3; r3.horizon = 10; r3.rank_ic = 0.03;
    ICResult r4; r4.horizon = 20; r4.rank_ic = 0.01;
    profile.results = {r1, r2, r3, r4};
    EXPECT_EQ(profile.peak_horizon(), 5);
}

// =============================================================================
// Basic stat computation tests (Eigen-based verification)
// =============================================================================

TEST(StatsTest, MeanComputation) {
    Eigen::VectorXd v(5);
    v << 2.0, 4.0, 6.0, 8.0, 10.0;
    EXPECT_DOUBLE_EQ(v.mean(), 6.0);
}

TEST(StatsTest, VarianceComputation) {
    Eigen::VectorXd v(4);
    v << 2.0, 4.0, 6.0, 8.0;
    double mean = v.mean();
    Eigen::VectorXd centered = v.array() - mean;
    double variance = centered.squaredNorm() / (v.size() - 1);
    EXPECT_NEAR(variance, 20.0 / 3.0, 1e-10);
}

TEST(StatsTest, SkewnessSymmetric) {
    Eigen::VectorXd v(5);
    v << -2.0, -1.0, 0.0, 1.0, 2.0;
    double mean = v.mean();
    double n = static_cast<double>(v.size());
    Eigen::VectorXd centered = v.array() - mean;
    double m2 = centered.squaredNorm() / n;
    double m3 = (centered.array().cube()).sum() / n;
    double skew = m3 / std::pow(m2, 1.5);
    EXPECT_NEAR(skew, 0.0, 1e-10);
}

TEST(StatsTest, KurtosisUniform) {
    Eigen::VectorXd v(5);
    v << -2.0, -1.0, 0.0, 1.0, 2.0;
    double mean = v.mean();
    double n = static_cast<double>(v.size());
    Eigen::VectorXd centered = v.array() - mean;
    double m2 = centered.squaredNorm() / n;
    double m4 = (centered.array().pow(4.0)).sum() / n;
    double excess_kurtosis = m4 / (m2 * m2) - 3.0;
    EXPECT_LT(excess_kurtosis, 0.0);
}

TEST(StatsTest, CovarianceSymmetric) {
    Eigen::MatrixXd returns(5, 2);
    returns << 0.01, 0.02,
               0.02, 0.01,
               -0.01, -0.02,
               0.03, 0.03,
               -0.02, -0.01;
    Eigen::VectorXd mean = returns.colwise().mean();
    Eigen::MatrixXd centered = returns.rowwise() - mean.transpose();
    Eigen::MatrixXd cov = (centered.transpose() * centered) / (returns.rows() - 1);
    EXPECT_NEAR(cov(0, 1), cov(1, 0), 1e-15);
    EXPECT_GT(cov(0, 0), 0.0);
}
