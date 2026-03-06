#include <gtest/gtest.h>
#include "trade/common/types.h"

using namespace trade;

// =============================================================================
// Price conversion tests
// =============================================================================

TEST(TypesTest, ToDoubleBasic) {
    // 12.3456 yuan = 123456 cents (4 decimal places)
    PriceCents cents = 123456;
    double d = to_double(cents);
    EXPECT_DOUBLE_EQ(d, 12.3456);
}

TEST(TypesTest, ToDoubleZero) {
    EXPECT_DOUBLE_EQ(to_double(0), 0.0);
}

TEST(TypesTest, ToDoubleNegative) {
    // Negative price (edge case, shouldn't happen in practice)
    PriceCents cents = -50000;
    EXPECT_DOUBLE_EQ(to_double(cents), -5.0);
}

TEST(TypesTest, ToCentsBasic) {
    double price = 12.3456;
    PriceCents cents = to_cents(price);
    EXPECT_EQ(cents, 123456);
}

TEST(TypesTest, ToCentsZero) {
    EXPECT_EQ(to_cents(0.0), 0);
}

TEST(TypesTest, ToCentsRoundTrip) {
    // Round-trip: double -> cents -> double should preserve 4 decimal places
    double original = 25.6789;
    PriceCents cents = to_cents(original);
    double recovered = to_double(cents);
    EXPECT_DOUBLE_EQ(recovered, original);
}

TEST(TypesTest, ToCentsRoundTripMultiple) {
    // Test multiple values for round-trip consistency
    std::vector<double> prices = {0.01, 1.0, 10.00, 99.9999, 100.0, 1234.5678};
    for (double p : prices) {
        PriceCents c = to_cents(p);
        double recovered = to_double(c);
        EXPECT_NEAR(recovered, p, 1e-4)
            << "Round-trip failed for price=" << p;
    }
}

TEST(TypesTest, ToCentsRounding) {
    // Values that need rounding to the nearest cent
    // 10.00005 * 10000 + 0.5 = 100001.0 -> 100001
    PriceCents cents = to_cents(10.00005);
    EXPECT_EQ(cents, 100001);
}

TEST(TypesTest, PriceScaleConstant) {
    EXPECT_DOUBLE_EQ(kPriceScale, 10000.0);
}

// =============================================================================
// Price limit percentage tests
// =============================================================================

TEST(TypesTest, PriceLimitPctMain) {
    EXPECT_DOUBLE_EQ(price_limit_pct(Board::kMain), 0.10);
}

TEST(TypesTest, PriceLimitPctST) {
    EXPECT_DOUBLE_EQ(price_limit_pct(Board::kST), 0.05);
}

TEST(TypesTest, PriceLimitPctSTAR) {
    EXPECT_DOUBLE_EQ(price_limit_pct(Board::kSTAR), 0.20);
}

TEST(TypesTest, PriceLimitPctChiNext) {
    EXPECT_DOUBLE_EQ(price_limit_pct(Board::kChiNext), 0.20);
}

TEST(TypesTest, PriceLimitPctBSE) {
    EXPECT_DOUBLE_EQ(price_limit_pct(Board::kBSE), 0.30);
}

TEST(TypesTest, PriceLimitPctNewIPOMainDay1) {
    EXPECT_DOUBLE_EQ(price_limit_pct(Board::kNewIPOMainDay1), 0.44);
}

TEST(TypesTest, PriceLimitPctNewIPOStarDay1) {
    // Effectively unlimited
    EXPECT_DOUBLE_EQ(price_limit_pct(Board::kNewIPOStarDay1), 10.0);
}

// =============================================================================
// Enum value tests
// =============================================================================

TEST(TypesTest, MarketEnumValues) {
    EXPECT_EQ(static_cast<uint8_t>(Market::kSH), 0);
    EXPECT_EQ(static_cast<uint8_t>(Market::kSZ), 1);
    EXPECT_EQ(static_cast<uint8_t>(Market::kBJ), 2);
    EXPECT_EQ(static_cast<uint8_t>(Market::kHK), 3);
    EXPECT_EQ(static_cast<uint8_t>(Market::kUS), 4);
    EXPECT_EQ(static_cast<uint8_t>(Market::kCrypto), 5);
}

TEST(TypesTest, BoardEnumValues) {
    EXPECT_EQ(static_cast<uint8_t>(Board::kMain), 0);
    EXPECT_EQ(static_cast<uint8_t>(Board::kST), 1);
    EXPECT_EQ(static_cast<uint8_t>(Board::kSTAR), 2);
    EXPECT_EQ(static_cast<uint8_t>(Board::kChiNext), 3);
    EXPECT_EQ(static_cast<uint8_t>(Board::kBSE), 4);
    EXPECT_EQ(static_cast<uint8_t>(Board::kNewIPOMainDay1), 5);
    EXPECT_EQ(static_cast<uint8_t>(Board::kNewIPOStarDay1), 6);
}

TEST(TypesTest, TradingStatusEnumValues) {
    EXPECT_EQ(static_cast<uint8_t>(TradingStatus::kNormal), 0);
    EXPECT_EQ(static_cast<uint8_t>(TradingStatus::kSuspended), 1);
    EXPECT_EQ(static_cast<uint8_t>(TradingStatus::kST), 2);
    EXPECT_EQ(static_cast<uint8_t>(TradingStatus::kStarST), 3);
    EXPECT_EQ(static_cast<uint8_t>(TradingStatus::kDelisting), 4);
}

TEST(TypesTest, SideEnumValues) {
    EXPECT_EQ(static_cast<uint8_t>(Side::kBuy), 0);
    EXPECT_EQ(static_cast<uint8_t>(Side::kSell), 1);
}

TEST(TypesTest, OrderStatusEnumValues) {
    EXPECT_EQ(static_cast<uint8_t>(OrderStatus::kPending), 0);
    EXPECT_EQ(static_cast<uint8_t>(OrderStatus::kFilled), 1);
    EXPECT_EQ(static_cast<uint8_t>(OrderStatus::kPartialFill), 2);
    EXPECT_EQ(static_cast<uint8_t>(OrderStatus::kCancelled), 3);
    EXPECT_EQ(static_cast<uint8_t>(OrderStatus::kRejected), 4);
}

TEST(TypesTest, RegimeEnumValues) {
    EXPECT_EQ(static_cast<uint8_t>(Regime::kBull), 0);
    EXPECT_EQ(static_cast<uint8_t>(Regime::kBear), 1);
    EXPECT_EQ(static_cast<uint8_t>(Regime::kShock), 2);
}

TEST(TypesTest, SentimentDirectionEnumValues) {
    EXPECT_EQ(static_cast<uint8_t>(SentimentDirection::kPositive), 0);
    EXPECT_EQ(static_cast<uint8_t>(SentimentDirection::kNeutral), 1);
    EXPECT_EQ(static_cast<uint8_t>(SentimentDirection::kNegative), 2);
}

TEST(TypesTest, AlertLevelEnumValues) {
    EXPECT_EQ(static_cast<uint8_t>(AlertLevel::kGreen), 0);
    EXPECT_EQ(static_cast<uint8_t>(AlertLevel::kYellow), 1);
    EXPECT_EQ(static_cast<uint8_t>(AlertLevel::kOrange), 2);
    EXPECT_EQ(static_cast<uint8_t>(AlertLevel::kRed), 3);
}

TEST(TypesTest, SWIndustryEnumValues) {
    EXPECT_EQ(static_cast<uint8_t>(SWIndustry::kAgriculture), 0);
    EXPECT_EQ(static_cast<uint8_t>(SWIndustry::kBanking), 17);
    EXPECT_EQ(static_cast<uint8_t>(SWIndustry::kPetroleum), 30);
    EXPECT_EQ(static_cast<uint8_t>(SWIndustry::kUnknown), 255);
}

TEST(TypesTest, SWIndustryCount) {
    EXPECT_EQ(kSWIndustryCount, 31u);
}
