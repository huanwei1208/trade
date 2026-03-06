#include <gtest/gtest.h>
#include "trade/model/bar.h"
#include "trade/normalizer/bar_normalizer.h"
#include "trade/storage/parquet_writer.h"
#include "trade/storage/parquet_reader.h"

#include <cstdio>
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
// Helper: create test bars
// =============================================================================
static std::vector<Bar> make_test_bars() {
    std::vector<Bar> bars;

    {
        Bar b;
        b.symbol = "600000.SH";
        b.date = make_date(2024, 1, 2);
        b.open = 10.50;
        b.high = 11.20;
        b.low = 10.30;
        b.close = 10.80;
        b.volume = 1000000;
        b.amount = 10800000.0;
        b.turnover_rate = 0.025;
        b.prev_close = 10.40;
        b.vwap = 10.80;
        bars.push_back(b);
    }

    {
        Bar b;
        b.symbol = "600000.SH";
        b.date = make_date(2024, 1, 3);
        b.open = 10.80;
        b.high = 11.50;
        b.low = 10.70;
        b.close = 11.30;
        b.volume = 1500000;
        b.amount = 16950000.0;
        b.turnover_rate = 0.038;
        b.prev_close = 10.80;
        b.vwap = 11.30;
        bars.push_back(b);
    }

    {
        Bar b;
        b.symbol = "600000.SH";
        b.date = make_date(2024, 1, 4);
        b.open = 11.30;
        b.high = 11.60;
        b.low = 10.90;
        b.close = 11.00;
        b.volume = 1200000;
        b.amount = 13200000.0;
        b.turnover_rate = 0.030;
        b.prev_close = 11.30;
        b.vwap = 11.00;
        bars.push_back(b);
    }

    return bars;
}

// =============================================================================
// Fixture: manages temp file lifecycle
// =============================================================================
class ParquetRoundTripTest : public ::testing::Test {
protected:
    std::string temp_path_;

    void SetUp() override {
        temp_path_ = "/tmp/trade_test_parquet_roundtrip.parquet";
        // Clean up any leftover from previous test run
        std::filesystem::remove(temp_path_);
    }

    void TearDown() override {
        std::filesystem::remove(temp_path_);
    }
};

// =============================================================================
// Write bars, read back, verify all fields match (full 20-column schema)
// =============================================================================

TEST_F(ParquetRoundTripTest, WriteAndReadBars) {
    auto original_bars = make_test_bars();

    // Write bars to parquet
    ParquetWriter::write_bars(temp_path_, original_bars);

    // Verify file exists
    ASSERT_TRUE(std::filesystem::exists(temp_path_));

    // Read bars back
    auto read_bars = ParquetReader::read_bars(temp_path_);

    // Verify count
    ASSERT_EQ(read_bars.size(), original_bars.size());

    // Verify each bar field by field
    for (size_t i = 0; i < original_bars.size(); ++i) {
        const auto& orig = original_bars[i];
        const auto& read = read_bars[i];

        EXPECT_EQ(read.symbol, orig.symbol)
            << "Symbol mismatch at index " << i;
        EXPECT_EQ(read.date, orig.date)
            << "Date mismatch at index " << i;
        EXPECT_NEAR(read.open, orig.open, 1e-6)
            << "Open mismatch at index " << i;
        EXPECT_NEAR(read.high, orig.high, 1e-6)
            << "High mismatch at index " << i;
        EXPECT_NEAR(read.low, orig.low, 1e-6)
            << "Low mismatch at index " << i;
        EXPECT_NEAR(read.close, orig.close, 1e-6)
            << "Close mismatch at index " << i;
        EXPECT_EQ(read.volume, orig.volume)
            << "Volume mismatch at index " << i;
        EXPECT_NEAR(read.amount, orig.amount, 1e-2)
            << "Amount mismatch at index " << i;
        EXPECT_NEAR(read.turnover_rate, orig.turnover_rate, 1e-6)
            << "Turnover rate mismatch at index " << i;
        EXPECT_NEAR(read.prev_close, orig.prev_close, 1e-6)
            << "Prev close mismatch at index " << i;
        EXPECT_NEAR(read.vwap, orig.vwap, 1e-6)
            << "VWAP mismatch at index " << i;
    }
}

TEST_F(ParquetRoundTripTest, RowCount) {
    auto bars = make_test_bars();
    ParquetWriter::write_bars(temp_path_, bars);

    int64_t count = ParquetReader::row_count(temp_path_);
    EXPECT_EQ(count, static_cast<int64_t>(bars.size()));
}

TEST_F(ParquetRoundTripTest, EmptyBars) {
    std::vector<Bar> empty_bars;
    ParquetWriter::write_bars(temp_path_, empty_bars);
    ASSERT_TRUE(std::filesystem::exists(temp_path_));

    auto read_bars = ParquetReader::read_bars(temp_path_);
    EXPECT_EQ(read_bars.size(), 0u);
}

TEST_F(ParquetRoundTripTest, ReadTable) {
    auto bars = make_test_bars();
    ParquetWriter::write_bars(temp_path_, bars);

    auto table = ParquetReader::read_table(temp_path_);
    ASSERT_NE(table, nullptr);
    EXPECT_EQ(table->num_rows(), static_cast<int64_t>(bars.size()));
    EXPECT_EQ(table->num_columns(), 20);
}

// =============================================================================
// Full schema round-trip: test extended fields (limit, status, fund flow)
// =============================================================================

class FullSchemaParquetTest : public ::testing::Test {
protected:
    std::string temp_path_;

    void SetUp() override {
        temp_path_ = "/tmp/trade_test_full_schema_parquet.parquet";
        std::filesystem::remove(temp_path_);
    }

    void TearDown() override {
        std::filesystem::remove(temp_path_);
    }
};

TEST_F(FullSchemaParquetTest, WriteAndReadFullSchema) {
    std::vector<Bar> bars;

    {
        Bar b;
        b.symbol = "600000.SH";
        b.date = make_date(2024, 1, 2);
        b.open = 10.50;
        b.high = 11.20;
        b.low = 10.30;
        b.close = 10.80;
        b.volume = 1000000;
        b.amount = 10800000.0;
        b.turnover_rate = 0.025;
        b.prev_close = 10.40;
        b.vwap = 10.80;
        b.board = Board::kMain;
        b.bar_status = TradingStatus::kNormal;
        bars.push_back(b);
    }

    BarNormalizer::compute_limits(bars, Board::kMain);

    ParquetWriter::write_bars(temp_path_, bars);
    ASSERT_TRUE(std::filesystem::exists(temp_path_));

    auto read = ParquetReader::read_bars(temp_path_);
    ASSERT_EQ(read.size(), 1u);

    EXPECT_EQ(read[0].symbol, "600000.SH");
    EXPECT_NEAR(read[0].limit_up, bars[0].limit_up, 0.01);
    EXPECT_NEAR(read[0].limit_down, bars[0].limit_down, 0.01);
    EXPECT_EQ(read[0].board, Board::kMain);
    EXPECT_EQ(read[0].bar_status, TradingStatus::kNormal);
}

// =============================================================================
// ParquetStore merge semantics for bars
// =============================================================================

TEST_F(ParquetRoundTripTest, MergeBarsByDate) {
    auto bars = make_test_bars();
    ParquetStore::write_bars(temp_path_, bars, ParquetStore::MergeMode::kReplace);

    std::vector<Bar> update;
    {
        Bar b = bars[1];
        b.close = 99.99;
        update.push_back(b);
    }
    ParquetStore::write_bars(temp_path_, update, ParquetStore::MergeMode::kMergeByKey);

    auto read = ParquetReader::read_bars(temp_path_);
    ASSERT_EQ(read.size(), bars.size());

    bool found = false;
    for (const auto& b : read) {
        if (b.date == bars[1].date) {
            found = true;
            EXPECT_NEAR(b.close, 99.99, 1e-6);
        }
    }
    EXPECT_TRUE(found);
}
