#include <gtest/gtest.h>
#include "trade/model/bar.h"
#include "trade/normalizer/bar_normalizer.h"
#include "trade/validator/data_validator.h"
#include "trade/storage/parquet_writer.h"
#include "trade/storage/parquet_reader.h"

#include <filesystem>
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
// Helper: create raw bars simulating provider output
// (out of order, no prev_close, no vwap)
// =============================================================================
static std::vector<Bar> create_raw_bars() {
    std::vector<Bar> bars;

    auto add_bar = [&](Date date, double open, double high, double low,
                       double close, Volume volume, double amount) {
        Bar b;
        b.symbol = "600000.SH";
        b.date = date;
        b.open = open;
        b.high = high;
        b.low = low;
        b.close = close;
        b.volume = volume;
        b.amount = amount;
        b.turnover_rate = 0.0;
        b.prev_close = 0.0;
        b.vwap = 0.0;
        bars.push_back(b);
    };

    // Intentionally out of date order to test sort
    // Day 5
    add_bar(make_date(2024, 1, 8), 11.80, 12.10, 11.50, 11.90, 1800000, 21420000.0);
    // Day 1
    add_bar(make_date(2024, 1, 2), 10.50, 11.00, 10.20, 10.80, 1200000, 12960000.0);
    // Day 4
    add_bar(make_date(2024, 1, 5), 11.50, 12.00, 11.30, 11.80, 1600000, 18880000.0);
    // Day 2
    add_bar(make_date(2024, 1, 3), 10.80, 11.30, 10.60, 11.20, 1400000, 15680000.0);
    // Day 3
    add_bar(make_date(2024, 1, 4), 11.20, 11.60, 10.90, 11.50, 1500000, 17250000.0);

    return bars;
}

// =============================================================================
// Fixture: manages temp files for integration test
// =============================================================================
class PipelineIntegrationTest : public ::testing::Test {
protected:
    std::string parquet_path_;

    void SetUp() override {
        parquet_path_ = "/tmp/trade_test_pipeline_integration.parquet";
        std::filesystem::remove(parquet_path_);
    }

    void TearDown() override {
        std::filesystem::remove(parquet_path_);
    }
};

// =============================================================================
// Full pipeline test: create -> normalize -> validate -> write -> read -> verify
// =============================================================================

TEST_F(PipelineIntegrationTest, FullPipeline) {
    // Step 1: Create raw bars (simulating data provider output)
    auto raw_bars = create_raw_bars();
    ASSERT_EQ(raw_bars.size(), 5u);

    // Step 2: Normalize (sort, fill prev_close, compute vwap)
    auto normalized_bars = BarNormalizer::normalize(std::move(raw_bars));

    // Verify sort order
    ASSERT_EQ(normalized_bars.size(), 5u);
    for (size_t i = 1; i < normalized_bars.size(); ++i) {
        EXPECT_LE(normalized_bars[i - 1].date, normalized_bars[i].date)
            << "Bars not sorted at index " << i;
    }

    // Verify dates are in expected order
    EXPECT_EQ(normalized_bars[0].date, make_date(2024, 1, 2));
    EXPECT_EQ(normalized_bars[1].date, make_date(2024, 1, 3));
    EXPECT_EQ(normalized_bars[2].date, make_date(2024, 1, 4));
    EXPECT_EQ(normalized_bars[3].date, make_date(2024, 1, 5));
    EXPECT_EQ(normalized_bars[4].date, make_date(2024, 1, 8));

    // Verify prev_close was filled
    EXPECT_NEAR(normalized_bars[1].prev_close, 10.80, 1e-6);
    EXPECT_NEAR(normalized_bars[2].prev_close, 11.20, 1e-6);
    EXPECT_NEAR(normalized_bars[3].prev_close, 11.50, 1e-6);
    EXPECT_NEAR(normalized_bars[4].prev_close, 11.80, 1e-6);

    // Verify vwap was computed (vwap = amount / volume)
    for (size_t i = 0; i < normalized_bars.size(); ++i) {
        if (normalized_bars[i].volume > 0) {
            double expected_vwap =
                normalized_bars[i].amount / static_cast<double>(normalized_bars[i].volume);
            EXPECT_NEAR(normalized_bars[i].vwap, expected_vwap, 1e-6)
                << "VWAP mismatch at index " << i;
        }
    }

    // Step 3: Validate
    QualityReport report = DataValidator::validate(normalized_bars);
    EXPECT_EQ(report.total_bars, 5);
    EXPECT_EQ(report.valid_bars, 5);
    EXPECT_EQ(report.invalid_bars, 0);
    EXPECT_EQ(report.duplicate_dates, 0);
    EXPECT_EQ(report.price_anomalies, 0);
    EXPECT_DOUBLE_EQ(report.quality_score(), 1.0);

    // Step 4: Write to parquet
    ParquetWriter::write_bars(parquet_path_, normalized_bars);
    ASSERT_TRUE(std::filesystem::exists(parquet_path_));

    // Step 5: Read back from parquet
    auto read_bars = ParquetReader::read_bars(parquet_path_);

    // Step 6: Verify all fields match after round-trip
    ASSERT_EQ(read_bars.size(), normalized_bars.size());

    for (size_t i = 0; i < normalized_bars.size(); ++i) {
        const auto& expected = normalized_bars[i];
        const auto& actual = read_bars[i];

        EXPECT_EQ(actual.symbol, expected.symbol)
            << "Symbol mismatch at index " << i;
        EXPECT_EQ(actual.date, expected.date)
            << "Date mismatch at index " << i;
        EXPECT_NEAR(actual.open, expected.open, 1e-6)
            << "Open mismatch at index " << i;
        EXPECT_NEAR(actual.high, expected.high, 1e-6)
            << "High mismatch at index " << i;
        EXPECT_NEAR(actual.low, expected.low, 1e-6)
            << "Low mismatch at index " << i;
        EXPECT_NEAR(actual.close, expected.close, 1e-6)
            << "Close mismatch at index " << i;
        EXPECT_EQ(actual.volume, expected.volume)
            << "Volume mismatch at index " << i;
        EXPECT_NEAR(actual.amount, expected.amount, 1e-2)
            << "Amount mismatch at index " << i;
        EXPECT_NEAR(actual.prev_close, expected.prev_close, 1e-6)
            << "Prev close mismatch at index " << i;
        EXPECT_NEAR(actual.vwap, expected.vwap, 1e-6)
            << "VWAP mismatch at index " << i;
    }

    // Step 7: Verify row count via reader utility
    int64_t count = ParquetReader::row_count(parquet_path_);
    EXPECT_EQ(count, 5);
}

// =============================================================================
// Pipeline with invalid data: ensure validation catches issues
// =============================================================================

TEST_F(PipelineIntegrationTest, PipelineWithInvalidData) {
    std::vector<Bar> bars;

    // Valid bar
    {
        Bar b;
        b.symbol = "600000.SH";
        b.date = make_date(2024, 1, 2);
        b.open = 10.50;
        b.high = 11.00;
        b.low = 10.20;
        b.close = 10.80;
        b.volume = 1200000;
        b.amount = 12960000.0;
        bars.push_back(b);
    }

    // Invalid bar: high < low
    {
        Bar b;
        b.symbol = "600000.SH";
        b.date = make_date(2024, 1, 3);
        b.open = 10.80;
        b.high = 10.50;  // high < low: invalid
        b.low = 11.00;
        b.close = 10.70;
        b.volume = 1000000;
        b.amount = 10700000.0;
        bars.push_back(b);
    }

    auto normalized = BarNormalizer::normalize(std::move(bars));

    QualityReport report = DataValidator::validate(normalized);
    EXPECT_GT(report.price_anomalies, 0);
}

// =============================================================================
// Pipeline with duplicate dates
// =============================================================================

TEST_F(PipelineIntegrationTest, PipelineWithDuplicateDates) {
    std::vector<Bar> bars;

    auto add_valid = [&](Date date, double close) {
        Bar b;
        b.symbol = "600000.SH";
        b.date = date;
        b.open = close;
        b.high = close + 0.5;
        b.low = close - 0.3;
        b.close = close;
        b.volume = 1000000;
        b.amount = close * 1000000.0;
        bars.push_back(b);
    };

    add_valid(make_date(2024, 1, 2), 10.50);
    add_valid(make_date(2024, 1, 3), 10.80);
    add_valid(make_date(2024, 1, 3), 10.90);  // duplicate date
    add_valid(make_date(2024, 1, 4), 11.00);

    auto normalized = BarNormalizer::normalize(std::move(bars));

    QualityReport report = DataValidator::validate(normalized);
    EXPECT_GE(report.duplicate_dates, 1);
}

// =============================================================================
// Pipeline with change_pct verification after normalization
// =============================================================================

TEST_F(PipelineIntegrationTest, ChangePctAfterNormalization) {
    auto raw_bars = create_raw_bars();
    auto normalized = BarNormalizer::normalize(std::move(raw_bars));

    // After normalization, prev_close should be filled, so change_pct works
    for (size_t i = 1; i < normalized.size(); ++i) {
        double pct = normalized[i].change_pct();
        // Change should be reasonable (within daily limits for A-shares)
        EXPECT_GT(pct, -0.50) << "Unreasonable change_pct at index " << i;
        EXPECT_LT(pct, 0.50) << "Unreasonable change_pct at index " << i;
    }
}

// =============================================================================
// Pipeline with date-filtered read
// =============================================================================

TEST_F(PipelineIntegrationTest, DateFilteredRead) {
    auto raw_bars = create_raw_bars();
    auto normalized = BarNormalizer::normalize(std::move(raw_bars));

    ParquetWriter::write_bars(parquet_path_, normalized);

    // Read with date filter: only bars between Jan 3 and Jan 5
    auto start = make_date(2024, 1, 3);
    auto end = make_date(2024, 1, 5);
    auto filtered = ParquetReader::read_bars(parquet_path_, start, end);

    EXPECT_GT(filtered.size(), 0u);
    EXPECT_LE(filtered.size(), normalized.size());
    for (const auto& bar : filtered) {
        EXPECT_GE(bar.date, start);
        EXPECT_LE(bar.date, end);
    }
}
