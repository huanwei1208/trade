#include <gtest/gtest.h>
#include <cmath>
#include <vector>

#include "trade/regime/regime_detector.h"

using namespace trade;

// =============================================================================
// RegimeDetector static helper tests
// =============================================================================

TEST(RegimeTest, SMABasic) {
    std::vector<double> prices = {10, 11, 12, 13, 14};
    double sma3 = RegimeDetector::sma(prices, 3);
    // mean of last 3: (12 + 13 + 14) / 3 = 13.0
    EXPECT_NEAR(sma3, 13.0, 1e-10);
}

TEST(RegimeTest, SMASinglePeriod) {
    std::vector<double> prices = {10, 20, 30};
    double sma1 = RegimeDetector::sma(prices, 1);
    EXPECT_NEAR(sma1, 30.0, 1e-10);
}

TEST(RegimeTest, SMAFullPeriod) {
    std::vector<double> prices = {1, 2, 3, 4, 5};
    double sma5 = RegimeDetector::sma(prices, 5);
    EXPECT_NEAR(sma5, 3.0, 1e-10);
}

TEST(RegimeTest, RealizedVolConstant) {
    std::vector<double> prices(30, 100.0);
    double vol = RegimeDetector::realized_vol(prices, 20);
    EXPECT_NEAR(vol, 0.0, 1e-10);
}

TEST(RegimeTest, RealizedVolPositive) {
    std::vector<double> prices;
    for (int i = 0; i < 30; ++i) {
        prices.push_back(100.0 + (i % 2 == 0 ? 2.0 : -2.0));
    }
    double vol = RegimeDetector::realized_vol(prices, 20);
    EXPECT_GT(vol, 0.0);
}

TEST(RegimeTest, TrendSlopeUptrend) {
    std::vector<double> prices;
    for (int i = 0; i < 100; ++i) {
        prices.push_back(100.0 + 0.5 * i);
    }
    double slope = RegimeDetector::trend_slope(prices, 60);
    EXPECT_GT(slope, 0.0);
}

TEST(RegimeTest, TrendSlopeDowntrend) {
    std::vector<double> prices;
    for (int i = 0; i < 100; ++i) {
        prices.push_back(200.0 - 0.5 * i);
    }
    double slope = RegimeDetector::trend_slope(prices, 60);
    EXPECT_LT(slope, 0.0);
}

TEST(RegimeTest, QuantileRank) {
    std::vector<double> dist = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10};
    // Value 5 should be around 50th percentile
    double q = RegimeDetector::quantile_rank(5.0, dist);
    EXPECT_NEAR(q, 0.5, 0.15);
    // Value 1 should be near 0
    double q_low = RegimeDetector::quantile_rank(1.0, dist);
    EXPECT_LE(q_low, 0.15);
    // Value 10 should be near 1
    double q_high = RegimeDetector::quantile_rank(10.0, dist);
    EXPECT_GE(q_high, 0.85);
}

// =============================================================================
// Regime detection tests
// =============================================================================

TEST(RegimeTest, DetectBullMarket) {
    // Build prices that are in a clear uptrend above 120DMA
    // with low volatility
    std::vector<double> prices;
    for (int i = 0; i < 200; ++i) {
        prices.push_back(3000.0 + 2.0 * i);
    }
    RegimeDetector::MarketBreadth breadth;
    breadth.total_stocks = 5000;
    breadth.up_stocks = 3500;  // 70% up ratio > 60%

    RegimeDetector detector;
    auto result = detector.detect(prices, breadth);

    // Index is well above 120DMA, up_ratio is high
    EXPECT_GT(result.index_above_dma_pct, 0.0);
    EXPECT_GT(result.up_ratio, 0.60);
    // Should detect bull or at least not shock
    if (result.annualised_vol < 0.22) {
        EXPECT_EQ(result.market_regime, Regime::kBull);
    }
}

TEST(RegimeTest, DetectBearMarket) {
    // Prices declining, below 120DMA
    std::vector<double> prices;
    for (int i = 0; i < 200; ++i) {
        prices.push_back(5000.0 - 5.0 * i);
    }
    RegimeDetector::MarketBreadth breadth;
    breadth.total_stocks = 5000;
    breadth.up_stocks = 2000;  // 40% < 45%

    RegimeDetector detector;
    auto result = detector.detect(prices, breadth);

    EXPECT_LT(result.index_above_dma_pct, 0.0);
    EXPECT_LT(result.up_ratio, 0.45);
    EXPECT_TRUE(result.trend_down);
    EXPECT_EQ(result.market_regime, Regime::kBear);
}

TEST(RegimeTest, DetectShockVolTrigger) {
    // Very volatile prices
    std::vector<double> prices;
    for (int i = 0; i < 200; ++i) {
        prices.push_back(3000.0 + (i % 2 == 0 ? 150.0 : -150.0));
    }
    RegimeDetector::MarketBreadth breadth;
    breadth.total_stocks = 5000;
    breadth.up_stocks = 2500;

    RegimeDetector detector;
    auto result = detector.detect(prices, breadth);

    // High volatility should trigger shock
    if (result.annualised_vol > 0.35) {
        EXPECT_EQ(result.market_regime, Regime::kShock);
        EXPECT_TRUE(result.shock_vol_trigger);
    }
}

TEST(RegimeTest, DetectShockSingleDayTrigger) {
    // Normal prices with a sudden crash
    std::vector<double> prices;
    for (int i = 0; i < 199; ++i) {
        prices.push_back(3000.0 + 0.1 * i);
    }
    prices.push_back(3000.0 * 0.95);  // -5% single day crash

    RegimeDetector::MarketBreadth breadth;
    breadth.total_stocks = 5000;
    breadth.up_stocks = 1000;

    RegimeDetector detector;
    auto result = detector.detect(prices, breadth);
    EXPECT_LT(result.single_day_return, -0.03);
    // Should trigger shock due to single day return
    if (std::abs(result.single_day_return) > 0.03) {
        EXPECT_TRUE(result.shock_day_trigger);
    }
}

// =============================================================================
// MarketBreadth tests
// =============================================================================

TEST(RegimeTest, MarketBreadthUpRatio) {
    RegimeDetector::MarketBreadth b;
    b.total_stocks = 5000;
    b.up_stocks = 3000;
    EXPECT_NEAR(b.up_ratio(), 0.6, 1e-10);
}

TEST(RegimeTest, MarketBreadthZeroStocks) {
    RegimeDetector::MarketBreadth b;
    b.total_stocks = 0;
    b.up_stocks = 0;
    EXPECT_DOUBLE_EQ(b.up_ratio(), 0.0);
}

// =============================================================================
// RegimeResult name tests
// =============================================================================

TEST(RegimeTest, RegimeResultNames) {
    RegimeDetector::RegimeResult r;
    r.market_regime = Regime::kBull;
    EXPECT_EQ(r.regime_name(), "Bull");
    r.market_regime = Regime::kBear;
    EXPECT_EQ(r.regime_name(), "Bear");
    r.market_regime = Regime::kShock;
    EXPECT_EQ(r.regime_name(), "Shock");
}

TEST(RegimeTest, VolRegimeNames) {
    RegimeDetector::RegimeResult r;
    r.vol_regime = RegimeDetector::VolRegime::kLow;
    EXPECT_EQ(r.vol_regime_name(), "LowVol");
    r.vol_regime = RegimeDetector::VolRegime::kNormal;
    EXPECT_EQ(r.vol_regime_name(), "NormalVol");
    r.vol_regime = RegimeDetector::VolRegime::kHigh;
    EXPECT_EQ(r.vol_regime_name(), "HighVol");
}

// =============================================================================
// Regime persistence tracking
// =============================================================================

TEST(RegimeTest, UpdateMaintainsState) {
    RegimeDetector detector;
    // Feed multiple days of bull data
    std::vector<double> prices;
    for (int i = 0; i < 200; ++i) {
        prices.push_back(3000.0 + 2.0 * i);
    }
    RegimeDetector::MarketBreadth breadth;
    breadth.total_stocks = 5000;
    breadth.up_stocks = 3500;

    // Call update multiple times
    for (int d = 0; d < 5; ++d) {
        prices.push_back(prices.back() + 2.0);
        detector.update(prices, breadth);
    }
    // After several updates, duration should increase
    EXPECT_GE(detector.regime_duration(), 1);
}
