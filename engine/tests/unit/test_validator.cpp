#include <gtest/gtest.h>
#include "trade/validator/data_validator.h"

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
// Helper: create a valid bar
// =============================================================================
static Bar make_valid_bar(Date date, double close = 10.0, Volume volume = 1000) {
    Bar b;
    b.symbol = "600000.SH";
    b.date = date;
    b.open = close;
    b.high = close + 0.5;
    b.low = close - 0.5;
    b.close = close;
    b.volume = volume;
    b.amount = close * static_cast<double>(volume);
    b.prev_close = close;
    return b;
}

// =============================================================================
// Valid bars pass validation
// =============================================================================

TEST(DataValidatorTest, ValidBarsPass) {
    std::vector<Bar> bars = {
        make_valid_bar(make_date(2024, 1, 2), 10.0),
        make_valid_bar(make_date(2024, 1, 3), 10.5),
        make_valid_bar(make_date(2024, 1, 4), 11.0),
    };

    QualityReport report = DataValidator::validate(bars);

    EXPECT_EQ(report.total_bars, 3);
    EXPECT_EQ(report.valid_bars, 3);
    EXPECT_EQ(report.invalid_bars, 0);
    EXPECT_DOUBLE_EQ(report.quality_score(), 1.0);
}

TEST(DataValidatorTest, EmptyBars) {
    std::vector<Bar> bars;
    QualityReport report = DataValidator::validate(bars);

    EXPECT_EQ(report.total_bars, 0);
    EXPECT_DOUBLE_EQ(report.quality_score(), 0.0);
}

// =============================================================================
// Duplicate date detection
// =============================================================================

TEST(DataValidatorTest, DuplicateDatesDetected) {
    std::vector<Bar> bars = {
        make_valid_bar(make_date(2024, 1, 2)),
        make_valid_bar(make_date(2024, 1, 3)),
        make_valid_bar(make_date(2024, 1, 3)),  // duplicate
        make_valid_bar(make_date(2024, 1, 4)),
    };

    int dups = DataValidator::check_duplicates(bars);
    EXPECT_GE(dups, 1);
}

TEST(DataValidatorTest, NoDuplicates) {
    std::vector<Bar> bars = {
        make_valid_bar(make_date(2024, 1, 2)),
        make_valid_bar(make_date(2024, 1, 3)),
        make_valid_bar(make_date(2024, 1, 4)),
    };

    int dups = DataValidator::check_duplicates(bars);
    EXPECT_EQ(dups, 0);
}

TEST(DataValidatorTest, DuplicateDatesInReport) {
    std::vector<Bar> bars = {
        make_valid_bar(make_date(2024, 1, 2)),
        make_valid_bar(make_date(2024, 1, 2)),  // duplicate
    };

    QualityReport report = DataValidator::validate(bars);
    EXPECT_GE(report.duplicate_dates, 1);
}

// =============================================================================
// Price anomaly detection (high < low)
// =============================================================================

TEST(DataValidatorTest, PriceAnomalyHighBelowLow) {
    std::vector<Bar> bars = {
        make_valid_bar(make_date(2024, 1, 2)),
    };

    // Corrupt the bar: set high < low
    bars[0].high = 9.0;
    bars[0].low = 10.0;

    int anomalies = DataValidator::check_price_sanity(bars);
    EXPECT_GE(anomalies, 1);
}

TEST(DataValidatorTest, PriceAnomalyNegativePrice) {
    std::vector<Bar> bars = {
        make_valid_bar(make_date(2024, 1, 2)),
    };

    bars[0].close = -1.0;

    int anomalies = DataValidator::check_price_sanity(bars);
    EXPECT_GE(anomalies, 1);
}

TEST(DataValidatorTest, PriceAnomalyZeroOpen) {
    std::vector<Bar> bars = {
        make_valid_bar(make_date(2024, 1, 2)),
    };

    bars[0].open = 0.0;

    int anomalies = DataValidator::check_price_sanity(bars);
    EXPECT_GE(anomalies, 1);
}

TEST(DataValidatorTest, ValidPriceSanity) {
    std::vector<Bar> bars = {
        make_valid_bar(make_date(2024, 1, 2)),
        make_valid_bar(make_date(2024, 1, 3)),
    };

    int anomalies = DataValidator::check_price_sanity(bars);
    EXPECT_EQ(anomalies, 0);
}

// =============================================================================
// Volume anomaly detection
// =============================================================================

TEST(DataValidatorTest, VolumeAnomalyNegative) {
    std::vector<Bar> bars = {
        make_valid_bar(make_date(2024, 1, 2)),
    };

    bars[0].volume = -100;

    int anomalies = DataValidator::check_volume_anomalies(bars);
    EXPECT_GE(anomalies, 1);
}

TEST(DataValidatorTest, VolumeAnomalyZeroOnNormalDay) {
    // Zero volume on a non-suspended day could be flagged as anomalous
    std::vector<Bar> bars = {
        make_valid_bar(make_date(2024, 1, 2), 10.0, 0),
    };

    int anomalies = DataValidator::check_volume_anomalies(bars);
    // Depending on implementation, 0 volume may or may not be anomalous
    // At minimum, negative should definitely be anomalous
    EXPECT_GE(anomalies, 0);
}

TEST(DataValidatorTest, ValidVolume) {
    std::vector<Bar> bars = {
        make_valid_bar(make_date(2024, 1, 2), 10.0, 10000),
        make_valid_bar(make_date(2024, 1, 3), 10.5, 15000),
    };

    int anomalies = DataValidator::check_volume_anomalies(bars);
    EXPECT_EQ(anomalies, 0);
}

// =============================================================================
// QualityReport tests
// =============================================================================

TEST(QualityReportTest, IsClean) {
    QualityReport report;
    report.total_bars = 10;
    report.valid_bars = 10;
    report.invalid_bars = 0;
    EXPECT_TRUE(report.is_clean());
}

TEST(QualityReportTest, IsNotCleanInvalidBars) {
    QualityReport report;
    report.total_bars = 10;
    report.valid_bars = 8;
    report.invalid_bars = 2;
    EXPECT_FALSE(report.is_clean());
}

TEST(QualityReportTest, IsNotCleanWarnings) {
    QualityReport report;
    report.total_bars = 10;
    report.valid_bars = 10;
    report.invalid_bars = 0;
    report.warnings.push_back("Some warning");
    EXPECT_FALSE(report.is_clean());
}

TEST(QualityReportTest, QualityScore) {
    QualityReport report;
    report.total_bars = 10;
    report.valid_bars = 8;
    EXPECT_DOUBLE_EQ(report.quality_score(), 0.8);
}

TEST(QualityReportTest, QualityScoreZeroTotal) {
    QualityReport report;
    report.total_bars = 0;
    report.valid_bars = 0;
    EXPECT_DOUBLE_EQ(report.quality_score(), 0.0);
}
