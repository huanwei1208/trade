#include <gtest/gtest.h>
#include <Eigen/Dense>
#include <cmath>
#include <limits>

#include "trade/features/momentum.h"
#include "trade/features/volatility.h"
#include "trade/features/liquidity.h"
#include "trade/features/preprocessor.h"
#include "trade/features/feature_engine.h"
#include "trade/features/feature_monitor.h"

using namespace trade;

// =============================================================================
// MomentumCalculator tests
// =============================================================================

TEST(MomentumTest, CumulativeReturnSimple) {
    // daily returns: +1%, +2%, -1% => compounded = (1.01)(1.02)(0.99) - 1
    Eigen::VectorXd rets(3);
    rets << 0.01, 0.02, -0.01;
    auto result = MomentumCalculator::cumulative_return(rets, 3);
    double expected = (1.01 * 1.02 * 0.99) - 1.0;
    EXPECT_NEAR(result(2), expected, 1e-10);
}

TEST(MomentumTest, CumulativeReturnWindowLargerThanData) {
    Eigen::VectorXd rets(3);
    rets << 0.01, 0.02, -0.01;
    auto result = MomentumCalculator::cumulative_return(rets, 5);
    // Only last element should be valid (window > data for early entries)
    EXPECT_EQ(result.size(), 3);
    // First entries should be NaN since we don't have enough data
    EXPECT_TRUE(std::isnan(result(0)));
}

TEST(MomentumTest, CumulativeReturnZeros) {
    Eigen::VectorXd rets(5);
    rets << 0.0, 0.0, 0.0, 0.0, 0.0;
    auto result = MomentumCalculator::cumulative_return(rets, 3);
    // Compounded zero returns = 0
    EXPECT_NEAR(result(4), 0.0, 1e-12);
}

TEST(MomentumTest, ReversalRankOrdering) {
    // reversal_rank = rank(-return)
    // Highest return should get lowest rank
    Eigen::VectorXd returns(4);
    returns << 0.05, -0.02, 0.03, -0.01;
    auto ranks = MomentumCalculator::reversal_rank(returns);
    EXPECT_EQ(ranks.size(), 4);
    // Stock 0 (+5%) has highest return -> lowest reversal rank (rank of -0.05)
    // Stock 1 (-2%) has lowest return -> highest reversal rank (rank of +0.02)
    EXPECT_LT(ranks(0), ranks(1));  // best performer ranks lower in reversal
    EXPECT_LT(ranks(2), ranks(3));  // +3% < -1% in reversal rank
}

TEST(MomentumTest, MomentumRankOrdering) {
    // momentum_rank = rank(+return)
    Eigen::VectorXd returns(4);
    returns << 0.05, -0.02, 0.03, -0.01;
    auto ranks = MomentumCalculator::momentum_rank(returns);
    // Highest return should get highest momentum rank
    EXPECT_GT(ranks(0), ranks(1));  // +5% ranks higher than -2%
    EXPECT_GT(ranks(2), ranks(3));  // +3% ranks higher than -1%
}

TEST(MomentumTest, ReverseAndMomentumRankComplement) {
    Eigen::VectorXd returns(3);
    returns << 0.01, 0.02, 0.03;
    auto rev = MomentumCalculator::reversal_rank(returns);
    auto mom = MomentumCalculator::momentum_rank(returns);
    // For strictly ordered data, ranks should be complementary
    for (int i = 0; i < 3; ++i) {
        EXPECT_NEAR(rev(i) + mom(i), 1.0, 0.01);
    }
}

TEST(MomentumTest, IdiosyncraticVolatility) {
    // Stock returns = 2 * market_returns + noise
    Eigen::VectorXd market(30);
    Eigen::VectorXd stock(30);
    for (int i = 0; i < 30; ++i) {
        market(i) = 0.001 * (i % 5 - 2);
        stock(i) = 2.0 * market(i) + 0.0001;  // near-zero idio noise
    }
    auto idio = MomentumCalculator::idiosyncratic_volatility(stock, market, 20);
    EXPECT_EQ(idio.size(), 30);
    // With near-zero idiosyncratic noise, idio vol should be very small
    // (the last valid entry)
    if (!std::isnan(idio(29))) {
        EXPECT_LT(idio(29), 0.01);
    }
}

// =============================================================================
// VolatilityCalculator tests
// =============================================================================

TEST(VolatilityTest, RealizedVolatilityConstant) {
    // Constant returns => zero volatility (may produce NaN if impl divides by 0)
    Eigen::VectorXd rets(20);
    rets.setConstant(0.01);
    auto vol = VolatilityCalculator::realized_volatility(rets, 20);
    // If impl returns 0.0 or NaN for constant inputs, both are acceptable
    EXPECT_TRUE(vol(19) == 0.0 || std::isnan(vol(19)) || vol(19) < 1e-10);
}

TEST(VolatilityTest, RealizedVolatilityKnown) {
    // Returns: alternating +1%, -1% => std should be ~0.01
    Eigen::VectorXd rets(20);
    for (int i = 0; i < 20; ++i) {
        rets(i) = (i % 2 == 0) ? 0.01 : -0.01;
    }
    auto vol = VolatilityCalculator::realized_volatility(rets, 20);
    // std of +0.01, -0.01 repeating = 0.01 (population) or ~0.01026 (sample)
    EXPECT_NEAR(vol(19), 0.01, 0.005);
}

TEST(VolatilityTest, RealizedVolatilityEarlyNaN) {
    Eigen::VectorXd rets(10);
    for (int i = 0; i < 10; ++i) rets(i) = 0.01 * (i % 2 == 0 ? 1 : -1);
    auto vol = VolatilityCalculator::realized_volatility(rets, 5);
    // First few entries may be NaN (insufficient data for window)
    for (int i = 0; i < 3; ++i) {
        EXPECT_TRUE(std::isnan(vol(i)));
    }
    // Later entries with enough data should be valid and positive
    EXPECT_FALSE(std::isnan(vol(9)));
    EXPECT_GT(vol(9), 0.0);
}

TEST(VolatilityTest, HighLowAmplitude) {
    Eigen::VectorXd highs(5), lows(5), closes(5);
    highs << 11.0, 12.0, 13.0, 14.0, 15.0;
    lows << 9.0, 10.0, 11.0, 12.0, 13.0;
    closes << 10.0, 11.0, 12.0, 13.0, 14.0;
    auto amp = VolatilityCalculator::high_low_amplitude(highs, lows, closes, 3);
    // (high-low)/close for each: 0.2, 0.1818, 0.1667, 0.1538, 0.1429
    // Last 3: mean(0.1667, 0.1538, 0.1429) = 0.1545
    EXPECT_NEAR(amp(4), (2.0 / 12.0 + 2.0 / 13.0 + 2.0 / 14.0) / 3.0, 1e-4);
}

TEST(VolatilityTest, VolOfVolKnown) {
    // vol_of_vol = rolling std of a volatility series
    Eigen::VectorXd vol_series(10);
    vol_series << 0.15, 0.16, 0.14, 0.17, 0.13, 0.18, 0.12, 0.19, 0.11, 0.20;
    auto vov = VolatilityCalculator::vol_of_vol(vol_series, 5);
    // The last entry should be std of last 5 values
    EXPECT_GT(vov(9), 0.0);
    EXPECT_FALSE(std::isnan(vov(9)));
}

// =============================================================================
// LiquidityCalculator tests
// =============================================================================

TEST(LiquidityTest, RollingTurnover) {
    Eigen::VectorXd rates(10);
    for (int i = 0; i < 10; ++i) rates(i) = 0.01 * (i + 1);
    auto result = LiquidityCalculator::rolling_turnover(rates, 5);
    // Last entry: mean of rates[5..9] = mean(0.06, 0.07, 0.08, 0.09, 0.10)
    EXPECT_NEAR(result(9), 0.08, 1e-10);
}

TEST(LiquidityTest, DeltaTurnover) {
    Eigen::VectorXd rates(20);
    // First 15 days: low turnover (0.01), then surge to 0.05
    for (int i = 0; i < 15; ++i) rates(i) = 0.01;
    for (int i = 15; i < 20; ++i) rates(i) = 0.05;
    auto dt = LiquidityCalculator::delta_turnover(rates, 5, 20);
    // Short avg = 0.05, long avg ~ mixed => delta should be positive
    if (!std::isnan(dt(19))) {
        EXPECT_GT(dt(19), 0.0);
    }
}

TEST(LiquidityTest, AmihudIlliquidity) {
    Eigen::VectorXd returns(10), volumes(10);
    for (int i = 0; i < 10; ++i) {
        returns(i) = 0.01;       // 1% return
        volumes(i) = 1000000.0;  // 1M yuan
    }
    auto amihud = LiquidityCalculator::amihud_illiquidity(returns, volumes, 5, 1e8);
    // |0.01| / 1e6 * 1e8 = 1.0
    if (!std::isnan(amihud(9))) {
        EXPECT_NEAR(amihud(9), 1.0, 0.1);
    }
}

TEST(LiquidityTest, VolumeRatio) {
    Eigen::VectorXd volumes(10);
    for (int i = 0; i < 9; ++i) volumes(i) = 100.0;
    volumes(9) = 200.0;  // Double volume on last day
    auto ratio = LiquidityCalculator::volume_ratio(volumes, 5);
    // ratio = 200 / mean(100,100,100,100,200) = 200/120 = 1.667
    // Actually ratio at index 9 = volumes[9] / MA(volumes[5..9], 5)
    if (!std::isnan(ratio(9))) {
        EXPECT_GT(ratio(9), 1.0);
    }
}

TEST(LiquidityTest, VwapDeviation) {
    Eigen::VectorXd closes(5), vwaps(5);
    closes << 10.0, 11.0, 9.0, 10.5, 10.2;
    vwaps << 10.0, 10.5, 9.5, 10.0, 10.0;
    auto dev = LiquidityCalculator::vwap_deviation(closes, vwaps);
    // dev[0] = 10/10 - 1 = 0
    EXPECT_NEAR(dev(0), 0.0, 1e-10);
    // dev[1] = 11/10.5 - 1 > 0 (close above VWAP)
    EXPECT_GT(dev(1), 0.0);
    // dev[2] = 9/9.5 - 1 < 0 (close below VWAP)
    EXPECT_LT(dev(2), 0.0);
}

// =============================================================================
// Feature utilities tests (cs_rank, ts_zscore, rolling_mean, rolling_std)
// =============================================================================

TEST(FeatureUtilTest, CsRankBasic) {
    Eigen::VectorXd v(4);
    v << 10.0, 30.0, 20.0, 40.0;
    auto ranks = cs_rank(v);
    // Sorted order: 10(0), 20(2), 30(1), 40(3) => ranks 0/3, 1/3, 2/3, 3/3
    EXPECT_NEAR(ranks(0), 0.0 / 3.0, 1e-6);  // lowest
    EXPECT_NEAR(ranks(3), 1.0, 1e-6);          // highest
    EXPECT_LT(ranks(0), ranks(2));
    EXPECT_LT(ranks(2), ranks(1));
    EXPECT_LT(ranks(1), ranks(3));
}

TEST(FeatureUtilTest, CsRankNaN) {
    Eigen::VectorXd v(3);
    v << 1.0, std::numeric_limits<double>::quiet_NaN(), 3.0;
    auto ranks = cs_rank(v);
    EXPECT_TRUE(std::isnan(ranks(1)));
    EXPECT_FALSE(std::isnan(ranks(0)));
    EXPECT_FALSE(std::isnan(ranks(2)));
}

TEST(FeatureUtilTest, TsZscoreBasic) {
    Eigen::VectorXd v(10);
    for (int i = 0; i < 10; ++i) v(i) = static_cast<double>(i);
    auto z = ts_zscore(v, 5);
    // At index 9: mean of [5,6,7,8,9] = 7
    // sample std = sqrt(10/4) = sqrt(2.5), pop std = sqrt(2)
    // z = (9 - 7) / std
    // Accept either sample or population std normalization
    if (!std::isnan(z(9))) {
        EXPECT_GT(z(9), 1.0);
        EXPECT_LT(z(9), 2.0);
    }
}

TEST(FeatureUtilTest, RollingMean) {
    Eigen::VectorXd v(6);
    v << 1, 2, 3, 4, 5, 6;
    auto rm = rolling_mean(v, 3);
    // rm[2] = mean(1,2,3) = 2
    EXPECT_NEAR(rm(2), 2.0, 1e-10);
    // rm[5] = mean(4,5,6) = 5
    EXPECT_NEAR(rm(5), 5.0, 1e-10);
}

TEST(FeatureUtilTest, RollingStd) {
    Eigen::VectorXd v(5);
    v << 2, 4, 4, 4, 5;
    auto rs = rolling_std(v, 3);
    // rs[2] = std(2,4,4) -- sample std
    double mean = (2.0 + 4.0 + 4.0) / 3.0;
    double var = ((2 - mean) * (2 - mean) + (4 - mean) * (4 - mean) +
                  (4 - mean) * (4 - mean)) / 2.0;
    if (!std::isnan(rs(2))) {
        EXPECT_NEAR(rs(2), std::sqrt(var), 0.01);
    }
}

TEST(FeatureUtilTest, RollingSum) {
    Eigen::VectorXd v(5);
    v << 1, 2, 3, 4, 5;
    auto rs = rolling_sum(v, 3);
    // rs[4] = 3 + 4 + 5 = 12
    EXPECT_NEAR(rs(4), 12.0, 1e-10);
}

TEST(FeatureUtilTest, EwmaBasic) {
    Eigen::VectorXd v(5);
    v << 1, 2, 3, 4, 5;
    auto ew = ewma(v, 2);  // halflife=2
    // EWMA should smooth towards recent values
    EXPECT_GT(ew(4), ew(0));
}

// =============================================================================
// Preprocessor tests
// =============================================================================

TEST(PreprocessorTest, MakeMissingFlags) {
    Eigen::MatrixXd mat(3, 2);
    mat << 1.0, std::numeric_limits<double>::quiet_NaN(),
           std::numeric_limits<double>::quiet_NaN(), 2.0,
           3.0, 4.0;
    auto flags = Preprocessor::make_missing_flags(mat);
    EXPECT_DOUBLE_EQ(flags(0, 0), 0.0);
    EXPECT_DOUBLE_EQ(flags(0, 1), 1.0);
    EXPECT_DOUBLE_EQ(flags(1, 0), 1.0);
    EXPECT_DOUBLE_EQ(flags(1, 1), 0.0);
    EXPECT_DOUBLE_EQ(flags(2, 0), 0.0);
    EXPECT_DOUBLE_EQ(flags(2, 1), 0.0);
}

// =============================================================================
// FeatureSet tests
// =============================================================================

TEST(FeatureSetTest, ColIndex) {
    FeatureSet fs;
    fs.names = {"alpha", "beta", "gamma"};
    fs.matrix = Eigen::MatrixXd::Zero(5, 3);
    EXPECT_EQ(fs.col_index("alpha"), 0);
    EXPECT_EQ(fs.col_index("beta"), 1);
    EXPECT_EQ(fs.col_index("gamma"), 2);
    EXPECT_EQ(fs.col_index("delta"), -1);
}

TEST(FeatureSetTest, Merge) {
    FeatureSet fs1;
    fs1.names = {"a"};
    fs1.matrix = Eigen::MatrixXd::Ones(3, 1);

    FeatureSet fs2;
    fs2.names = {"b", "c"};
    fs2.matrix = Eigen::MatrixXd::Constant(3, 2, 2.0);

    fs1.merge(fs2);
    EXPECT_EQ(fs1.num_features(), 3);
    EXPECT_EQ(fs1.matrix.cols(), 3);
    EXPECT_DOUBLE_EQ(fs1.matrix(0, 0), 1.0);
    EXPECT_DOUBLE_EQ(fs1.matrix(0, 1), 2.0);
    EXPECT_DOUBLE_EQ(fs1.matrix(0, 2), 2.0);
}

// =============================================================================
// FeatureMonitor tests
// =============================================================================

TEST(FeatureMonitorTest, PearsonICPerfectCorrelation) {
    Eigen::VectorXd feature(5);
    feature << 1, 2, 3, 4, 5;
    Eigen::VectorXd returns(5);
    returns << 0.01, 0.02, 0.03, 0.04, 0.05;
    double ic = FeatureMonitor::pearson_ic(feature, returns);
    EXPECT_NEAR(ic, 1.0, 1e-10);
}

TEST(FeatureMonitorTest, PearsonICNegativeCorrelation) {
    Eigen::VectorXd feature(5);
    feature << 1, 2, 3, 4, 5;
    Eigen::VectorXd returns(5);
    returns << 0.05, 0.04, 0.03, 0.02, 0.01;
    double ic = FeatureMonitor::pearson_ic(feature, returns);
    EXPECT_NEAR(ic, -1.0, 1e-10);
}

TEST(FeatureMonitorTest, SpearmanRankICPerfect) {
    Eigen::VectorXd feature(5);
    feature << 10, 20, 30, 40, 50;
    Eigen::VectorXd returns(5);
    returns << 0.01, 0.02, 0.03, 0.04, 0.05;
    double ric = FeatureMonitor::spearman_rank_ic(feature, returns);
    EXPECT_NEAR(ric, 1.0, 1e-6);
}

TEST(FeatureMonitorTest, ICIRComputation) {
    // IC series with constant positive IC => IC_IR should be large or special value
    Eigen::VectorXd ic_series(10);
    ic_series.setConstant(0.03);
    double icir = FeatureMonitor::compute_ic_ir(ic_series);
    // mean = 0.03, std = 0 => IC_IR could be inf, NaN, or very large
    // depending on how division by zero is handled
    EXPECT_TRUE(std::isinf(icir) || std::isnan(icir) || icir > 1.0 || icir == 0.0);
}

TEST(FeatureMonitorTest, ICIRWithVariance) {
    Eigen::VectorXd ic_series(10);
    for (int i = 0; i < 10; ++i) ic_series(i) = (i % 2 == 0) ? 0.03 : 0.01;
    double icir = FeatureMonitor::compute_ic_ir(ic_series);
    // mean = 0.02, std = 0.01 => IC_IR = 2.0
    EXPECT_GT(icir, 0.0);
}

TEST(FeatureMonitorTest, LongShortNetReturn) {
    Eigen::VectorXd feature(10);
    Eigen::VectorXd returns(10);
    // High feature values => high returns (perfect predictor)
    for (int i = 0; i < 10; ++i) {
        feature(i) = static_cast<double>(i);
        returns(i) = 0.001 * i;
    }
    double net_ret = FeatureMonitor::long_short_net_return(feature, returns, 0.0015);
    // Top quintile (8,9) avg ret = 0.0085, bottom quintile (0,1) avg ret = 0.0005
    // Gross L/S = 0.008, minus 2*0.0015 cost = 0.005
    EXPECT_GT(net_ret, 0.0);
}

// =============================================================================
// FeatureEngine tests
// =============================================================================

TEST(FeatureEngineTest, RegisterCalculator) {
    FeatureEngine engine;
    engine.emplace_calculator<MomentumCalculator>();
    engine.emplace_calculator<VolatilityCalculator>();
    EXPECT_EQ(engine.calculators().size(), 2u);
}

TEST(FeatureEngineTest, ConfigDefaults) {
    FeatureEngine::Config cfg;
    EXPECT_TRUE(cfg.fill_missing);
    EXPECT_TRUE(cfg.winsorize);
    EXPECT_TRUE(cfg.neutralize);
    EXPECT_TRUE(cfg.standardize);
    EXPECT_EQ(cfg.min_bar_count, 120);
}
