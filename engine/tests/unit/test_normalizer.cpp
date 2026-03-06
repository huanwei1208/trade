#include <gtest/gtest.h>
#include "trade/normalizer/bar_normalizer.h"

#include <algorithm>
#include <vector>

using namespace trade;

// =============================================================================
// Helper: create a date from year/month/day
// =============================================================================
static Date make_date(int year, int month, int day) {
    return std::chrono::sys_days{
        std::chrono::year{year} / std::chrono::month{static_cast<unsigned>(month)} /
        std::chrono::day{static_cast<unsigned>(day)}};
}

// =============================================================================
// Helper: create a bar with date, open, high, low, close, volume, amount
// =============================================================================
static Bar make_bar(Date date, double open, double high, double low,
                    double close, Volume volume, double amount = 0.0) {
    Bar b;
    b.symbol = "600000.SH";
    b.date = date;
    b.open = open;
    b.high = high;
    b.low = low;
    b.close = close;
    b.volume = volume;
    b.amount = amount;
    return b;
}

// =============================================================================
// sort_by_date tests
// =============================================================================

TEST(BarNormalizerTest, SortByDateAscending) {
    std::vector<Bar> bars = {
        make_bar(make_date(2024, 1, 3), 11.0, 12.0, 10.0, 11.5, 1000),
        make_bar(make_date(2024, 1, 1), 10.0, 11.0, 9.5, 10.5, 800),
        make_bar(make_date(2024, 1, 2), 10.5, 11.5, 10.0, 11.0, 900),
    };

    BarNormalizer::sort_by_date(bars);

    ASSERT_EQ(bars.size(), 3u);
    EXPECT_EQ(bars[0].date, make_date(2024, 1, 1));
    EXPECT_EQ(bars[1].date, make_date(2024, 1, 2));
    EXPECT_EQ(bars[2].date, make_date(2024, 1, 3));
}

TEST(BarNormalizerTest, SortByDateAlreadySorted) {
    std::vector<Bar> bars = {
        make_bar(make_date(2024, 1, 1), 10.0, 11.0, 9.5, 10.5, 800),
        make_bar(make_date(2024, 1, 2), 10.5, 11.5, 10.0, 11.0, 900),
    };

    BarNormalizer::sort_by_date(bars);

    EXPECT_EQ(bars[0].date, make_date(2024, 1, 1));
    EXPECT_EQ(bars[1].date, make_date(2024, 1, 2));
}

TEST(BarNormalizerTest, SortByDateEmpty) {
    std::vector<Bar> bars;
    BarNormalizer::sort_by_date(bars);
    EXPECT_TRUE(bars.empty());
}

// =============================================================================
// fill_prev_close tests
// =============================================================================

TEST(BarNormalizerTest, FillPrevClose) {
    std::vector<Bar> bars = {
        make_bar(make_date(2024, 1, 1), 10.0, 11.0, 9.5, 10.5, 800),
        make_bar(make_date(2024, 1, 2), 10.5, 11.5, 10.0, 11.0, 900),
        make_bar(make_date(2024, 1, 3), 11.0, 12.0, 10.5, 11.5, 1000),
    };

    BarNormalizer::fill_prev_close(bars);

    // First bar has no previous bar, so prev_close stays 0 (or whatever default)
    EXPECT_DOUBLE_EQ(bars[0].prev_close, 0.0);
    // Second bar: prev_close should be close of first bar
    EXPECT_DOUBLE_EQ(bars[1].prev_close, 10.5);
    // Third bar: prev_close should be close of second bar
    EXPECT_DOUBLE_EQ(bars[2].prev_close, 11.0);
}

TEST(BarNormalizerTest, FillPrevCloseSingleBar) {
    std::vector<Bar> bars = {
        make_bar(make_date(2024, 1, 1), 10.0, 11.0, 9.5, 10.5, 800),
    };

    BarNormalizer::fill_prev_close(bars);
    EXPECT_DOUBLE_EQ(bars[0].prev_close, 0.0);
}

TEST(BarNormalizerTest, FillPrevCloseEmpty) {
    std::vector<Bar> bars;
    // Should not crash
    BarNormalizer::fill_prev_close(bars);
    EXPECT_TRUE(bars.empty());
}

// =============================================================================
// compute_vwap tests
// =============================================================================

TEST(BarNormalizerTest, ComputeVwap) {
    std::vector<Bar> bars = {
        make_bar(make_date(2024, 1, 1), 10.0, 11.0, 9.5, 10.5, 1000, 10500.0),
        make_bar(make_date(2024, 1, 2), 10.5, 11.5, 10.0, 11.0, 2000, 22000.0),
    };

    BarNormalizer::compute_vwap(bars);

    // vwap = amount / volume
    EXPECT_NEAR(bars[0].vwap, 10500.0 / 1000.0, 1e-6);
    EXPECT_NEAR(bars[1].vwap, 22000.0 / 2000.0, 1e-6);
}

TEST(BarNormalizerTest, ComputeVwapZeroVolume) {
    std::vector<Bar> bars = {
        make_bar(make_date(2024, 1, 1), 10.0, 10.0, 10.0, 10.0, 0, 0.0),
    };

    // Should not crash; vwap should be 0 (or close when volume is 0)
    BarNormalizer::compute_vwap(bars);
    // With zero volume, vwap is typically set to 0 or close
    EXPECT_TRUE(bars[0].vwap == 0.0 || bars[0].vwap == bars[0].close);
}

// =============================================================================
// Full normalize pipeline test
// =============================================================================

TEST(BarNormalizerTest, NormalizeFullPipeline) {
    // Create bars out of order, without prev_close or vwap
    std::vector<Bar> bars = {
        make_bar(make_date(2024, 1, 3), 11.0, 12.0, 10.5, 11.5, 1500, 17250.0),
        make_bar(make_date(2024, 1, 1), 10.0, 11.0, 9.5, 10.5, 1000, 10500.0),
        make_bar(make_date(2024, 1, 2), 10.5, 11.5, 10.0, 11.0, 1200, 13200.0),
    };

    auto normalized = BarNormalizer::normalize(std::move(bars));

    // Should be sorted by date
    ASSERT_EQ(normalized.size(), 3u);
    EXPECT_EQ(normalized[0].date, make_date(2024, 1, 1));
    EXPECT_EQ(normalized[1].date, make_date(2024, 1, 2));
    EXPECT_EQ(normalized[2].date, make_date(2024, 1, 3));

    // prev_close should be filled
    EXPECT_DOUBLE_EQ(normalized[1].prev_close, 10.5);
    EXPECT_DOUBLE_EQ(normalized[2].prev_close, 11.0);

    // vwap should be computed
    EXPECT_NEAR(normalized[0].vwap, 10500.0 / 1000.0, 1e-6);
    EXPECT_NEAR(normalized[1].vwap, 13200.0 / 1200.0, 1e-6);
    EXPECT_NEAR(normalized[2].vwap, 17250.0 / 1500.0, 1e-6);
}

TEST(BarNormalizerTest, NormalizeEmpty) {
    std::vector<Bar> bars;
    auto result = BarNormalizer::normalize(std::move(bars));
    EXPECT_TRUE(result.empty());
}
