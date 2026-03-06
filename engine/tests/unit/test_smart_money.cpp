#include <gtest/gtest.h>
#include "trade/features/smart_money_signal.h"
#include "trade/model/bar.h"

#include <Eigen/Dense>
#include <cmath>
#include <vector>

using namespace trade;

// ---------------------------------------------------------------------------
// money_flow_multiplier tests
// ---------------------------------------------------------------------------

TEST(SmartMoneyTest, MFM_NeutralClose) {
    // close == midpoint of high-low → MFM = 0
    Eigen::VectorXd h(3), l(3), c(3);
    h << 10.0, 20.0, 30.0;
    l <<  8.0, 18.0, 28.0;
    c <<  9.0, 19.0, 29.0;   // exactly mid

    auto mfm = SmartMoneyCalculator::money_flow_multiplier(h, l, c);
    ASSERT_EQ(mfm.size(), 3);
    for (int i = 0; i < 3; ++i) {
        EXPECT_NEAR(mfm(i), 0.0, 1e-9) << "i=" << i;
    }
}

TEST(SmartMoneyTest, MFM_UpperClose) {
    // close == high → MFM = +1 (strong buying)
    Eigen::VectorXd h(1), l(1), c(1);
    h << 10.0; l << 8.0; c << 10.0;
    auto mfm = SmartMoneyCalculator::money_flow_multiplier(h, l, c);
    EXPECT_NEAR(mfm(0), 1.0, 1e-9);
}

TEST(SmartMoneyTest, MFM_LowerClose) {
    // close == low → MFM = -1 (strong selling)
    Eigen::VectorXd h(1), l(1), c(1);
    h << 10.0; l << 8.0; c << 8.0;
    auto mfm = SmartMoneyCalculator::money_flow_multiplier(h, l, c);
    EXPECT_NEAR(mfm(0), -1.0, 1e-9);
}

TEST(SmartMoneyTest, MFM_ZeroRange_ReturnsNaN) {
    // high == low → undefined MFM
    Eigen::VectorXd h(1), l(1), c(1);
    h << 10.0; l << 10.0; c << 10.0;
    auto mfm = SmartMoneyCalculator::money_flow_multiplier(h, l, c);
    EXPECT_TRUE(std::isnan(mfm(0)));
}

// ---------------------------------------------------------------------------
// chaikin_money_flow tests
// ---------------------------------------------------------------------------

TEST(SmartMoneyTest, CMF_AllUpperClose) {
    // Every bar closes at high → MFM = +1 → CMF = +1
    int n = 10;
    Eigen::VectorXd mfm(n), vol(n);
    mfm.setConstant(1.0);
    vol.setConstant(100.0);

    auto cmf5 = SmartMoneyCalculator::chaikin_money_flow(mfm, vol, 5);
    // First 4 entries should be NaN (warmup)
    for (int i = 0; i < 4; ++i) {
        EXPECT_TRUE(std::isnan(cmf5(i))) << "i=" << i;
    }
    for (int i = 4; i < n; ++i) {
        EXPECT_NEAR(cmf5(i), 1.0, 1e-9) << "i=" << i;
    }
}

TEST(SmartMoneyTest, CMF_AllLowerClose) {
    int n = 10;
    Eigen::VectorXd mfm(n), vol(n);
    mfm.setConstant(-1.0);
    vol.setConstant(100.0);

    auto cmf5 = SmartMoneyCalculator::chaikin_money_flow(mfm, vol, 5);
    for (int i = 4; i < n; ++i) {
        EXPECT_NEAR(cmf5(i), -1.0, 1e-9) << "i=" << i;
    }
}

TEST(SmartMoneyTest, CMF_InsufficientData_AllNaN) {
    int n = 3;
    Eigen::VectorXd mfm(n), vol(n);
    mfm.setConstant(1.0);
    vol.setConstant(100.0);

    auto cmf5 = SmartMoneyCalculator::chaikin_money_flow(mfm, vol, 5);
    for (int i = 0; i < n; ++i) {
        EXPECT_TRUE(std::isnan(cmf5(i))) << "i=" << i;
    }
}

// ---------------------------------------------------------------------------
// SmartMoneyCalculator::compute tests
// ---------------------------------------------------------------------------

namespace {

// Build a synthetic BarSeries with uniform OHLCV.
BarSeries make_series(const std::string& sym, int n_bars,
                      double hi, double lo, double cl, int64_t vol) {
    BarSeries bs;
    bs.symbol = sym;
    bs.bars.reserve(n_bars);
    auto base = std::chrono::sys_days{std::chrono::year{2024} / std::chrono::January / 1};
    for (int i = 0; i < n_bars; ++i) {
        Bar b;
        b.date   = base + std::chrono::days{i};
        b.open   = lo;
        b.high   = hi;
        b.low    = lo;
        b.close  = cl;
        b.volume = vol;
        b.amount = static_cast<double>(vol) * cl;
        bs.bars.push_back(b);
    }
    return bs;
}

} // namespace

TEST(SmartMoneyTest, Compute_BullClose_PositiveCMF) {
    // close == high → MFM = +1 → CMF always +1
    auto bs = make_series("000001.SZ", 25, /*hi*/10.0, /*lo*/8.0, /*cl*/10.0, 1000);
    std::unordered_map<Symbol, Instrument> inst;

    SmartMoneyCalculator calc;
    auto fs = calc.compute({bs}, inst);

    ASSERT_EQ(fs.num_features(), 2);
    ASSERT_EQ(fs.num_observations(), 1);

    // smart_money_flow_5d
    int idx5  = fs.col_index("smart_money_flow_5d");
    int idx20 = fs.col_index("smart_money_flow_20d");
    ASSERT_GE(idx5,  0);
    ASSERT_GE(idx20, 0);

    EXPECT_NEAR(fs.matrix(0, idx5),  1.0, 1e-9);
    EXPECT_NEAR(fs.matrix(0, idx20), 1.0, 1e-9);
}

TEST(SmartMoneyTest, Compute_BearClose_NegativeCMF) {
    // close == low → MFM = -1
    auto bs = make_series("000001.SZ", 25, 10.0, 8.0, /*cl*/8.0, 1000);
    std::unordered_map<Symbol, Instrument> inst;

    SmartMoneyCalculator calc;
    auto fs = calc.compute({bs}, inst);

    int idx5  = fs.col_index("smart_money_flow_5d");
    int idx20 = fs.col_index("smart_money_flow_20d");
    EXPECT_NEAR(fs.matrix(0, idx5),  -1.0, 1e-9);
    EXPECT_NEAR(fs.matrix(0, idx20), -1.0, 1e-9);
}

TEST(SmartMoneyTest, Compute_TooFewBars_NaN) {
    auto bs = make_series("000001.SZ", 3, 10.0, 8.0, 9.0, 1000);
    std::unordered_map<Symbol, Instrument> inst;

    SmartMoneyCalculator calc;
    auto fs = calc.compute({bs}, inst);

    ASSERT_EQ(fs.num_observations(), 1);
    EXPECT_TRUE(std::isnan(fs.matrix(0, 0)));
    EXPECT_TRUE(std::isnan(fs.matrix(0, 1)));
}

TEST(SmartMoneyTest, Compute_EmptySeries_ReturnsEmpty) {
    SmartMoneyCalculator calc;
    std::unordered_map<Symbol, Instrument> inst;
    auto fs = calc.compute({}, inst);
    EXPECT_EQ(fs.num_observations(), 0);
}
