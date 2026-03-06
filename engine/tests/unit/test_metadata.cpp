#include <gtest/gtest.h>
#include "trade/storage/metadata_store.h"
#include "trade/model/instrument.h"

#include <filesystem>
#include <memory>

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
// Helper: create a test instrument
// =============================================================================
static Instrument make_instrument(const std::string& symbol,
                                   const std::string& name,
                                   Market market,
                                   Board board,
                                   SWIndustry industry) {
    Instrument inst;
    inst.symbol = symbol;
    inst.name = name;
    inst.market = market;
    inst.board = board;
    inst.industry = industry;
    inst.list_date = make_date(2000, 1, 1);
    inst.status = TradingStatus::kNormal;
    return inst;
}

// =============================================================================
// Fixture: creates an in-memory SQLite metadata store
// =============================================================================
class MetadataStoreTest : public ::testing::Test {
protected:
    std::unique_ptr<MetadataStore> store_;

    void SetUp() override {
        store_ = std::make_unique<MetadataStore>(":memory:");
    }
};

// =============================================================================
// Instrument CRUD tests
// =============================================================================

TEST_F(MetadataStoreTest, UpsertAndGetInstrument) {
    auto inst = make_instrument("600000.SH", "Pudong Bank", Market::kSH,
                                Board::kMain, SWIndustry::kBanking);
    store_->upsert_instrument(inst);

    auto result = store_->get_instrument("600000.SH");
    ASSERT_TRUE(result.has_value());
    EXPECT_EQ(result->symbol, "600000.SH");
    EXPECT_EQ(result->name, "Pudong Bank");
    EXPECT_EQ(result->market, Market::kSH);
    EXPECT_EQ(result->market_name, "Shanghai");
    EXPECT_EQ(result->market_label(), "Shanghai");
    EXPECT_EQ(result->board, Board::kMain);
    EXPECT_EQ(result->industry, SWIndustry::kBanking);
}

TEST_F(MetadataStoreTest, GetNonExistentInstrument) {
    auto result = store_->get_instrument("999999.XX");
    EXPECT_FALSE(result.has_value());
}

TEST_F(MetadataStoreTest, UpsertUpdatesExisting) {
    auto inst = make_instrument("600000.SH", "Pudong Bank", Market::kSH,
                                Board::kMain, SWIndustry::kBanking);
    store_->upsert_instrument(inst);

    // Update the name
    inst.name = "Pudong Development Bank";
    store_->upsert_instrument(inst);

    auto result = store_->get_instrument("600000.SH");
    ASSERT_TRUE(result.has_value());
    EXPECT_EQ(result->name, "Pudong Development Bank");
}

TEST_F(MetadataStoreTest, GetAllInstruments) {
    store_->upsert_instrument(
        make_instrument("600000.SH", "A", Market::kSH, Board::kMain, SWIndustry::kBanking));
    store_->upsert_instrument(
        make_instrument("000001.SZ", "B", Market::kSZ, Board::kMain, SWIndustry::kBanking));
    store_->upsert_instrument(
        make_instrument("300001.SZ", "C", Market::kSZ, Board::kChiNext, SWIndustry::kComputer));

    auto all = store_->get_all_instruments();
    EXPECT_EQ(all.size(), 3u);
}

// =============================================================================
// Query by market/industry tests
// =============================================================================

TEST_F(MetadataStoreTest, GetInstrumentsByMarket) {
    store_->upsert_instrument(
        make_instrument("600000.SH", "A", Market::kSH, Board::kMain, SWIndustry::kBanking));
    store_->upsert_instrument(
        make_instrument("600001.SH", "B", Market::kSH, Board::kMain, SWIndustry::kComputer));
    store_->upsert_instrument(
        make_instrument("000001.SZ", "C", Market::kSZ, Board::kMain, SWIndustry::kBanking));

    auto sh_instruments = store_->get_instruments_by_market(Market::kSH);
    EXPECT_EQ(sh_instruments.size(), 2u);

    auto sz_instruments = store_->get_instruments_by_market(Market::kSZ);
    EXPECT_EQ(sz_instruments.size(), 1u);

    auto hk_instruments = store_->get_instruments_by_market(Market::kHK);
    EXPECT_EQ(hk_instruments.size(), 0u);
}

TEST_F(MetadataStoreTest, GetInstrumentsByIndustry) {
    store_->upsert_instrument(
        make_instrument("600000.SH", "A", Market::kSH, Board::kMain, SWIndustry::kBanking));
    store_->upsert_instrument(
        make_instrument("000001.SZ", "B", Market::kSZ, Board::kMain, SWIndustry::kBanking));
    store_->upsert_instrument(
        make_instrument("300001.SZ", "C", Market::kSZ, Board::kChiNext, SWIndustry::kComputer));

    auto banking = store_->get_instruments_by_industry(SWIndustry::kBanking);
    EXPECT_EQ(banking.size(), 2u);

    auto computer = store_->get_instruments_by_industry(SWIndustry::kComputer);
    EXPECT_EQ(computer.size(), 1u);

    auto mining = store_->get_instruments_by_industry(SWIndustry::kMining);
    EXPECT_EQ(mining.size(), 0u);
}

// =============================================================================
// Download tracking tests
// =============================================================================

TEST_F(MetadataStoreTest, RecordDownloadAndQueryLastDate) {
    Date start = make_date(2024, 1, 1);
    Date end = make_date(2024, 1, 31);

    store_->record_download("600000.SH", start, end, 22);

    auto last_date = store_->last_download_date("600000.SH");
    ASSERT_TRUE(last_date.has_value());
    EXPECT_EQ(*last_date, end);
}

TEST_F(MetadataStoreTest, LastDownloadDateNonExistent) {
    auto last_date = store_->last_download_date("999999.XX");
    EXPECT_FALSE(last_date.has_value());
}

TEST_F(MetadataStoreTest, RecordDownloadUpdatesLastDate) {
    Date start1 = make_date(2024, 1, 1);
    Date end1 = make_date(2024, 1, 31);
    store_->record_download("600000.SH", start1, end1, 22);

    Date start2 = make_date(2024, 2, 1);
    Date end2 = make_date(2024, 2, 28);
    store_->record_download("600000.SH", start2, end2, 19);

    auto last_date = store_->last_download_date("600000.SH");
    ASSERT_TRUE(last_date.has_value());
    EXPECT_EQ(*last_date, end2);
}

TEST_F(MetadataStoreTest, SymbolsNeedingUpdate) {
    Date end1 = make_date(2024, 1, 15);
    Date end2 = make_date(2024, 2, 15);

    // Instrument A: downloaded up to Jan 15
    store_->upsert_instrument(
        make_instrument("600000.SH", "A", Market::kSH, Board::kMain, SWIndustry::kBanking));
    store_->record_download("600000.SH", make_date(2024, 1, 1), end1, 10);

    // Instrument B: downloaded up to Feb 15
    store_->upsert_instrument(
        make_instrument("000001.SZ", "B", Market::kSZ, Board::kMain, SWIndustry::kBanking));
    store_->record_download("000001.SZ", make_date(2024, 2, 1), end2, 10);

    // Cutoff: Feb 1 -- only A should need update (its last download is Jan 15 < Feb 1)
    Date cutoff = make_date(2024, 2, 1);
    auto needing_update = store_->symbols_needing_update(cutoff);

    EXPECT_EQ(needing_update.size(), 1u);
    if (!needing_update.empty()) {
        EXPECT_EQ(needing_update[0], "600000.SH");
    }
}

// =============================================================================
// File-based MetadataStore test (temp file)
// =============================================================================

class MetadataStoreFileTest : public ::testing::Test {
protected:
    std::string temp_db_path_;

    void SetUp() override {
        temp_db_path_ = "/tmp/trade_test_metadata.db";
        std::filesystem::remove(temp_db_path_);
    }

    void TearDown() override {
        std::filesystem::remove(temp_db_path_);
    }
};

TEST_F(MetadataStoreFileTest, PersistAcrossInstances) {
    {
        MetadataStore store(temp_db_path_);
        store.upsert_instrument(
            make_instrument("600000.SH", "Test", Market::kSH, Board::kMain, SWIndustry::kBanking));
    }

    // Re-open the store from the same file
    {
        MetadataStore store(temp_db_path_);
        auto result = store.get_instrument("600000.SH");
        ASSERT_TRUE(result.has_value());
        EXPECT_EQ(result->symbol, "600000.SH");
        EXPECT_EQ(result->name, "Test");
    }
}

// =============================================================================
// Incremental watermark tests
// =============================================================================

TEST_F(MetadataStoreTest, UpsertAndGetWatermarkDate) {
    auto date1 = make_date(2024, 1, 31);
    auto date2 = make_date(2024, 2, 29);

    store_->upsert_watermark("eastmoney", "cn_a_daily_bar", "600000.SH", date1);
    auto wm1 = store_->last_watermark_date("eastmoney", "cn_a_daily_bar", "600000.SH");
    ASSERT_TRUE(wm1.has_value());
    EXPECT_EQ(*wm1, date1);

    store_->upsert_watermark("eastmoney", "cn_a_daily_bar", "600000.SH", date2,
                             R"({"cursor":"test"})");
    auto wm2 = store_->last_watermark_date("eastmoney", "cn_a_daily_bar", "600000.SH");
    ASSERT_TRUE(wm2.has_value());
    EXPECT_EQ(*wm2, date2);
}
