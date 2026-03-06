#pragma once

#include <cstdint>
#include <string>
#include <chrono>
#include <optional>
#include <vector>
#include <unordered_map>

namespace trade {

// Date represented as days since epoch (1970-01-01)
using Date = std::chrono::sys_days;
using Timestamp = std::chrono::system_clock::time_point;

// Price in cents to avoid floating point issues in exact comparisons
// For display/calculation, convert: price_double = price_cents / 10000.0
// Using 4 decimal places for precision (e.g., 12.3456 -> 123456)
using PriceCents = int64_t;
constexpr double kPriceScale = 10000.0;

inline double to_double(PriceCents p) { return static_cast<double>(p) / kPriceScale; }
inline PriceCents to_cents(double p) { return static_cast<PriceCents>(p * kPriceScale + 0.5); }

// Volume in shares
using Volume = int64_t;

// Amount in yuan * 100 (cents)
using AmountCents = int64_t;

// Symbol identifier: "600000.SH", "000001.SZ"
using Symbol = std::string;

// Market identifiers
enum class Market : uint8_t {
    kSH = 0,   // Shanghai
    kSZ = 1,   // Shenzhen
    kBJ = 2,   // Beijing (BSE)
    kHK = 3,   // Hong Kong
    kUS = 4,   // US
    kCrypto = 5,
};

// Board type - determines price limit rules
enum class Board : uint8_t {
    kMain = 0,          // 主板 ±10%
    kST = 1,            // ST/*ST ±5%
    kSTAR = 2,          // 科创板 ±20%
    kChiNext = 3,       // 创业板 ±20%
    kBSE = 4,           // 北交所 ±30%
    kNewIPOMainDay1 = 5, // 主板新股首日 ±44%
    kNewIPOStarDay1 = 6, // 科创/创业板新股首日 无限制
};

// Price limit percentage for each board
inline double price_limit_pct(Board b) {
    switch (b) {
        case Board::kMain: return 0.10;
        case Board::kST: return 0.05;
        case Board::kSTAR: return 0.20;
        case Board::kChiNext: return 0.20;
        case Board::kBSE: return 0.30;
        case Board::kNewIPOMainDay1: return 0.44;
        case Board::kNewIPOStarDay1: return 10.0; // effectively unlimited
    }
    return 0.10;
}

// Trading status
enum class TradingStatus : uint8_t {
    kNormal = 0,
    kSuspended = 1,   // 停牌
    kST = 2,          // ST
    kStarST = 3,      // *ST
    kDelisting = 4,   // 退市整理期
};

// Order side
enum class Side : uint8_t {
    kBuy = 0,
    kSell = 1,
};

// Order status
enum class OrderStatus : uint8_t {
    kPending = 0,
    kFilled = 1,
    kPartialFill = 2,
    kCancelled = 3,
    kRejected = 4,
};

// Market regime
enum class Regime : uint8_t {
    kBull = 0,
    kBear = 1,
    kShock = 2,   // High volatility / crash
};

// Sentiment direction
enum class SentimentDirection : uint8_t {
    kPositive = 0,
    kNeutral = 1,
    kNegative = 2,
};

// Risk alert level
enum class AlertLevel : uint8_t {
    kGreen = 0,
    kYellow = 1,
    kOrange = 2,
    kRed = 3,
};

// Shenwan Level-1 industry codes (31 industries)
enum class SWIndustry : uint8_t {
    kAgriculture = 0,
    kMining = 1,
    kChemical = 2,
    kSteel = 3,
    kNonFerrousMetal = 4,
    kElectronics = 5,
    kAuto = 6,
    kHouseholdAppliance = 7,
    kFoodBeverage = 8,
    kTextile = 9,
    kLightManufacturing = 10,
    kMedicine = 11,
    kUtilities = 12,
    kTransportation = 13,
    kRealEstate = 14,
    kCommerce = 15,
    kSocialService = 16,
    kBanking = 17,
    kNonBankFinancial = 18,
    kConstruction = 19,
    kBuildingMaterial = 20,
    kMechanicalEquipment = 21,
    kDefense = 22,
    kComputer = 23,
    kMedia = 24,
    kTelecom = 25,
    kEnvironment = 26,
    kElectricalEquipment = 27,
    kBeauty = 28,
    kCoal = 29,
    kPetroleum = 30,
    kUnknown = 255,
};

constexpr size_t kSWIndustryCount = 31;

} // namespace trade

// Hash specialization for Date (sys_days) to use in unordered containers
template <>
struct std::hash<trade::Date> {
    size_t operator()(const trade::Date& d) const noexcept {
        return std::hash<int64_t>{}(d.time_since_epoch().count());
    }
};
