#include <gtest/gtest.h>
#include "trade/model/bar.h"
#include "trade/normalizer/bar_normalizer.h"

using namespace trade;

// =============================================================================
// Helper: create a basic valid bar
// =============================================================================
static Bar make_bar(const std::string& symbol, double open, double high,
                    double low, double close, Volume volume,
                    double prev_close = 0.0) {
    Bar b;
    b.symbol = symbol;
    b.open = open;
    b.high = high;
    b.low = low;
    b.close = close;
    b.volume = volume;
    b.prev_close = prev_close;
    return b;
}

// =============================================================================
// change_pct tests
// =============================================================================

TEST(BarTest, ChangePctPositive) {
    Bar b = make_bar("600000.SH", 10.0, 11.0, 9.5, 11.0, 1000, 10.0);
    EXPECT_NEAR(b.change_pct(), 0.10, 1e-9);
}

TEST(BarTest, ChangePctNegative) {
    Bar b = make_bar("600000.SH", 10.0, 10.5, 9.0, 9.0, 1000, 10.0);
    EXPECT_NEAR(b.change_pct(), -0.10, 1e-9);
}

TEST(BarTest, ChangePctZero) {
    Bar b = make_bar("600000.SH", 10.0, 10.5, 9.5, 10.0, 1000, 10.0);
    EXPECT_DOUBLE_EQ(b.change_pct(), 0.0);
}

TEST(BarTest, ChangePctNoPrevClose) {
    Bar b = make_bar("600000.SH", 10.0, 11.0, 9.5, 11.0, 1000, 0.0);
    EXPECT_DOUBLE_EQ(b.change_pct(), 0.0);
}

// =============================================================================
// amplitude tests
// =============================================================================

TEST(BarTest, AmplitudeBasic) {
    Bar b = make_bar("600000.SH", 10.0, 11.0, 9.0, 10.5, 1000, 10.0);
    EXPECT_NEAR(b.amplitude(), 0.20, 1e-9);
}

TEST(BarTest, AmplitudeZeroPrevClose) {
    Bar b = make_bar("600000.SH", 10.0, 11.0, 9.0, 10.5, 1000, 0.0);
    EXPECT_DOUBLE_EQ(b.amplitude(), 0.0);
}

TEST(BarTest, AmplitudeFlat) {
    Bar b = make_bar("600000.SH", 10.0, 10.0, 10.0, 10.0, 1000, 10.0);
    EXPECT_DOUBLE_EQ(b.amplitude(), 0.0);
}

// =============================================================================
// open_gap tests
// =============================================================================

TEST(BarTest, OpenGapUp) {
    Bar b = make_bar("600000.SH", 10.5, 11.0, 10.0, 10.8, 1000, 10.0);
    EXPECT_NEAR(b.open_gap(), 0.05, 1e-9);
}

TEST(BarTest, OpenGapDown) {
    Bar b = make_bar("600000.SH", 9.5, 10.0, 9.0, 9.8, 1000, 10.0);
    EXPECT_NEAR(b.open_gap(), -0.05, 1e-9);
}

TEST(BarTest, OpenGapZeroPrevClose) {
    Bar b = make_bar("600000.SH", 10.0, 11.0, 9.0, 10.5, 1000, 0.0);
    EXPECT_DOUBLE_EQ(b.open_gap(), 0.0);
}

// =============================================================================
// is_valid tests
// =============================================================================

TEST(BarTest, IsValidGood) {
    Bar b = make_bar("600000.SH", 10.0, 11.0, 9.5, 10.5, 1000);
    EXPECT_TRUE(b.is_valid());
}

TEST(BarTest, IsValidEmptySymbol) {
    Bar b = make_bar("", 10.0, 11.0, 9.5, 10.5, 1000);
    EXPECT_FALSE(b.is_valid());
}

TEST(BarTest, IsValidZeroOpen) {
    Bar b = make_bar("600000.SH", 0.0, 11.0, 9.5, 10.5, 1000);
    EXPECT_FALSE(b.is_valid());
}

TEST(BarTest, IsValidHighBelowOpen) {
    Bar b = make_bar("600000.SH", 11.0, 10.0, 9.5, 10.5, 1000);
    EXPECT_FALSE(b.is_valid());
}

TEST(BarTest, IsValidLowAboveOpen) {
    Bar b = make_bar("600000.SH", 9.0, 11.0, 10.0, 10.5, 1000);
    EXPECT_FALSE(b.is_valid());
}

TEST(BarTest, IsValidZeroLow) {
    Bar b = make_bar("600000.SH", 10.0, 11.0, 0.0, 10.5, 1000);
    EXPECT_FALSE(b.is_valid());
}

TEST(BarTest, IsValidZeroClose) {
    Bar b = make_bar("600000.SH", 10.0, 11.0, 9.5, 0.0, 1000);
    EXPECT_FALSE(b.is_valid());
}

TEST(BarTest, IsValidZeroVolume) {
    Bar b = make_bar("600000.SH", 10.0, 11.0, 9.5, 10.5, 0);
    EXPECT_TRUE(b.is_valid());
}

TEST(BarTest, IsValidNegativeVolume) {
    Bar b = make_bar("600000.SH", 10.0, 11.0, 9.5, 10.5, -1);
    EXPECT_FALSE(b.is_valid());
}

// =============================================================================
// BarNormalizer::compute_limits tests
// =============================================================================

TEST(ComputeLimitsTest, Main) {
    std::vector<Bar> bars;
    Bar b;
    b.symbol = "600000.SH";
    b.prev_close = 10.0;
    b.close = 10.50;
    b.open = 10.50;
    b.high = 10.50;
    b.low = 10.50;
    b.volume = 1000;
    bars.push_back(b);

    BarNormalizer::compute_limits(bars, Board::kMain);

    EXPECT_NEAR(bars[0].limit_up, 11.00, 0.01);
    EXPECT_NEAR(bars[0].limit_down, 9.00, 0.01);
    EXPECT_FALSE(bars[0].hit_limit_up);
    EXPECT_FALSE(bars[0].hit_limit_down);
}

TEST(ComputeLimitsTest, ST) {
    std::vector<Bar> bars;
    Bar b;
    b.symbol = "000001.SZ";
    b.prev_close = 5.0;
    b.close = 5.25;
    b.open = 5.0;
    b.high = 5.25;
    b.low = 5.0;
    b.volume = 1000;
    bars.push_back(b);

    BarNormalizer::compute_limits(bars, Board::kST);

    EXPECT_NEAR(bars[0].limit_up, 5.25, 0.01);
    EXPECT_NEAR(bars[0].limit_down, 4.75, 0.01);
    EXPECT_TRUE(bars[0].hit_limit_up);
    EXPECT_FALSE(bars[0].hit_limit_down);
}

TEST(ComputeLimitsTest, ChiNext) {
    std::vector<Bar> bars;
    Bar b;
    b.symbol = "300001.SZ";
    b.prev_close = 20.0;
    b.close = 16.01;
    b.open = 20.0;
    b.high = 20.0;
    b.low = 16.01;
    b.volume = 1000;
    bars.push_back(b);

    BarNormalizer::compute_limits(bars, Board::kChiNext);

    EXPECT_NEAR(bars[0].limit_up, 24.00, 0.01);
    EXPECT_NEAR(bars[0].limit_down, 16.00, 0.01);
    EXPECT_FALSE(bars[0].hit_limit_up);
    EXPECT_FALSE(bars[0].hit_limit_down);
}

TEST(ComputeLimitsTest, HitLimitDown) {
    std::vector<Bar> bars;
    Bar b;
    b.symbol = "600000.SH";
    b.prev_close = 10.0;
    b.close = 9.00;
    b.open = 10.0;
    b.high = 10.0;
    b.low = 9.0;
    b.volume = 1000;
    bars.push_back(b);

    BarNormalizer::compute_limits(bars, Board::kMain);

    EXPECT_TRUE(bars[0].hit_limit_down);
    EXPECT_FALSE(bars[0].hit_limit_up);
}

TEST(ComputeLimitsTest, BSE) {
    std::vector<Bar> bars;
    Bar b;
    b.symbol = "830001.BJ";
    b.prev_close = 10.0;
    b.close = 12.99;
    b.open = 10.0;
    b.high = 12.99;
    b.low = 10.0;
    b.volume = 1000;
    bars.push_back(b);

    BarNormalizer::compute_limits(bars, Board::kBSE);

    EXPECT_NEAR(bars[0].limit_up, 13.00, 0.01);
    EXPECT_NEAR(bars[0].limit_down, 7.00, 0.01);
    EXPECT_FALSE(bars[0].hit_limit_up);
    EXPECT_FALSE(bars[0].hit_limit_down);
}

TEST(ComputeLimitsTest, Rounding) {
    std::vector<Bar> bars;
    Bar b;
    b.symbol = "600000.SH";
    b.prev_close = 13.37;
    b.close = 14.00;
    b.open = 14.00;
    b.high = 14.00;
    b.low = 14.00;
    b.volume = 1000;
    bars.push_back(b);

    BarNormalizer::compute_limits(bars, Board::kMain);

    EXPECT_NEAR(bars[0].limit_up, 14.71, 0.01);
    EXPECT_NEAR(bars[0].limit_down, 12.03, 0.01);
}

// =============================================================================
// BarSeries tests
// =============================================================================

TEST(BarSeriesTest, BasicOperations) {
    BarSeries bs;
    bs.symbol = "600000.SH";
    EXPECT_TRUE(bs.empty());
    EXPECT_EQ(bs.size(), 0u);

    bs.bars.push_back(make_bar("600000.SH", 10.0, 11.0, 9.5, 10.5, 1000));
    bs.bars.push_back(make_bar("600000.SH", 10.5, 12.0, 10.0, 11.0, 2000));

    EXPECT_FALSE(bs.empty());
    EXPECT_EQ(bs.size(), 2u);
    EXPECT_DOUBLE_EQ(bs[0].open, 10.0);
    EXPECT_DOUBLE_EQ(bs[1].close, 11.0);
}
