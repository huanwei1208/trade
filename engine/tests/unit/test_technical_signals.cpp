#include <gtest/gtest.h>
#include "trade/features/technical_signals.h"
#include "trade/model/bar.h"
#include "trade/common/types.h"

#include <chrono>
#include <cmath>
#include <vector>

using namespace trade;

// Helper: build a synthetic Bar with given close/high/low/volume/turnover
static Bar make_bar(int day_offset, double close, double high = 0.0, double low = 0.0,
                    int64_t volume = 100000, double turnover = 0.01) {
    Bar b;
    b.symbol = "TEST.SH";
    auto epoch = std::chrono::sys_days{std::chrono::year{2023} / std::chrono::January / 1};
    b.date     = epoch + std::chrono::days{day_offset};
    b.close    = close;
    b.high     = (high > 0.0) ? high : close * 1.01;
    b.low      = (low  > 0.0) ? low  : close * 0.99;
    b.open     = close;
    b.prev_close = close * 0.99;
    b.volume   = volume;
    b.amount   = static_cast<double>(volume) * close;
    b.turnover_rate = turnover;
    return b;
}

// Helper: build a bar series with linearly rising prices
static std::vector<Bar> rising_bars(int count, double start = 10.0, double step = 0.1) {
    std::vector<Bar> bars;
    bars.reserve(count);
    for (int i = 0; i < count; ++i) {
        double price = start + i * step;
        bars.push_back(make_bar(i, price, price * 1.02, price * 0.98));
    }
    return bars;
}

// Helper: flat price bars
static std::vector<Bar> flat_bars(int count, double price = 10.0) {
    std::vector<Bar> bars;
    bars.reserve(count);
    for (int i = 0; i < count; ++i) {
        bars.push_back(make_bar(i, price));
    }
    return bars;
}

// =============================================================================
// Test: fewer than minimum required bars returns default signal
// =============================================================================

TEST(TechnicalSignals, ComputeSignalsRequiresMinBars) {
    // With fewer than 10 bars most fields must stay at their defaults
    std::vector<Bar> tiny_bars = rising_bars(5);
    TechnicalSignal sig = compute_signals(tiny_bars);

    // Momentum fields that need 20+ bars should be 0 (default)
    EXPECT_FLOAT_EQ(sig.momentum_20d, 0.0f);
    EXPECT_FLOAT_EQ(sig.momentum_60d, 0.0f);
    EXPECT_FLOAT_EQ(sig.volatility_20d, 0.0f);
    // liquidity_20d needs 20 bars too
    EXPECT_FLOAT_EQ(sig.liquidity_20d, 0.0f);
    // MA trend needs 60 bars
    EXPECT_FLOAT_EQ(sig.ma_trend, 0.0f);
}

// Empty bars must also return default without crashing
TEST(TechnicalSignals, EmptyBarsReturnsDefault) {
    std::vector<Bar> empty;
    TechnicalSignal sig = compute_signals(empty);
    EXPECT_FLOAT_EQ(sig.rsi_14, 50.0f);
    EXPECT_EQ(sig.kdj_zone, 1);
    EXPECT_EQ(sig.macd_cross, 0);
}

// =============================================================================
// Test: momentum_20d is computed correctly with known input
// =============================================================================

TEST(TechnicalSignals, MomentumIsCorrect) {
    // Build exactly 21 bars with a known price path
    // close[0] = 100.0, close[20] = 110.0 => momentum_20d = (110-100)/100 = 0.10
    std::vector<Bar> bars;
    bars.reserve(21);
    for (int i = 0; i <= 20; ++i) {
        double price = 100.0 + i * 0.5;  // linear from 100 to 110
        bars.push_back(make_bar(i, price, price * 1.01, price * 0.99));
    }
    TechnicalSignal sig = compute_signals(bars);
    // close[20]=110, close[0]=100 => momentum_20d = 0.10
    EXPECT_NEAR(sig.momentum_20d, 0.10f, 0.001f);
}

// =============================================================================
// Test: Bollinger band position is within a reasonable range
// =============================================================================

TEST(TechnicalSignals, BollingerPositionIsInRange) {
    // Rising bars with 80 data points
    auto bars = rising_bars(80);
    TechnicalSignal sig = compute_signals(bars);
    // bb_position formula: (close - lower) / (upper - lower) * 2 - 1
    // For prices far from the band it could reach +-2, but typically well within [-1.5, 1.5]
    EXPECT_GE(sig.bb_position, -1.5f);
    EXPECT_LE(sig.bb_position, 1.5f);
}

// =============================================================================
// Additional quality tests
// =============================================================================

TEST(TechnicalSignals, RSIZoneOversoldOnFallingBars) {
    // Consistently falling prices should drive RSI towards oversold zone
    std::vector<Bar> bars;
    bars.reserve(60);
    for (int i = 0; i < 60; ++i) {
        double price = 100.0 - i * 0.8;  // falling
        bars.push_back(make_bar(i, std::max(price, 1.0)));
    }
    TechnicalSignal sig = compute_signals(bars);
    // RSI should be in oversold territory
    EXPECT_LT(sig.rsi_14, 40.0f);
    EXPECT_EQ(sig.rsi_zone, 0);  // oversold zone
}

TEST(TechnicalSignals, MATrendBullishOnRisingBars) {
    // 80 bars of steadily rising prices: MA5 > MA20 > MA60
    auto bars = rising_bars(80);
    TechnicalSignal sig = compute_signals(bars);
    EXPECT_FLOAT_EQ(sig.ma_trend, 1.0f);
}

TEST(TechnicalSignals, MATrendBearishOnFallingBars) {
    std::vector<Bar> bars;
    bars.reserve(80);
    for (int i = 0; i < 80; ++i) {
        double price = 100.0 - i * 0.5;
        bars.push_back(make_bar(i, std::max(price, 1.0)));
    }
    TechnicalSignal sig = compute_signals(bars);
    EXPECT_FLOAT_EQ(sig.ma_trend, -1.0f);
}

TEST(TechnicalSignals, VolatilityPositiveOnFluctuatingBars) {
    std::vector<Bar> bars;
    bars.reserve(25);
    for (int i = 0; i < 25; ++i) {
        double price = 10.0 + (i % 2 == 0 ? 1.0 : -1.0);
        bars.push_back(make_bar(i, price, price + 0.5, price - 0.5));
    }
    TechnicalSignal sig = compute_signals(bars);
    EXPECT_GT(sig.volatility_20d, 0.0f);
}

TEST(TechnicalSignals, LiquidityReflectsTurnoverRate) {
    std::vector<Bar> bars;
    bars.reserve(25);
    for (int i = 0; i < 25; ++i) {
        Bar b = make_bar(i, 10.0, 10.1, 9.9, 100000, 0.02);
        bars.push_back(b);
    }
    TechnicalSignal sig = compute_signals(bars);
    EXPECT_NEAR(sig.liquidity_20d, 0.02f, 0.001f);
}

TEST(TechnicalSignals, ComputeSignalSeriesRespectWarmup) {
    auto bars = rising_bars(80);
    auto series = compute_signal_series(bars, 60);
    // Should have 80 - 60 + 1 = 21 entries
    EXPECT_EQ(static_cast<int>(series.size()), 21);
}

TEST(TechnicalSignals, ComputeSignalSeriesTooFewBars) {
    auto bars = rising_bars(10);
    auto series = compute_signal_series(bars, 60);
    // Not enough bars to produce any entries
    EXPECT_TRUE(series.empty());
}

TEST(TechnicalSignals, VolumeBreakoutAboveOneOnHighVolume) {
    // First 20 bars: low volume. Last bar: 5x volume.
    std::vector<Bar> bars;
    bars.reserve(22);
    for (int i = 0; i < 21; ++i) {
        bars.push_back(make_bar(i, 10.0, 10.1, 9.9, 100000, 0.01));
    }
    Bar spike = make_bar(21, 10.0, 10.1, 9.9, 500000, 0.01);
    bars.push_back(spike);
    TechnicalSignal sig = compute_signals(bars);
    EXPECT_GT(sig.volume_breakout, 2.0f);
}
