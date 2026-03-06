#pragma once

#include "trade/common/types.h"
#include <string>
#include <optional>

namespace trade {

inline const char* market_name_from_enum(Market market) {
    switch (market) {
        case Market::kSH: return "Shanghai";
        case Market::kSZ: return "Shenzhen";
        case Market::kBJ: return "Beijing";
        case Market::kHK: return "Hong Kong";
        case Market::kUS: return "US";
        case Market::kCrypto: return "Crypto";
    }
    return "Unknown";
}

// Static instrument metadata
struct Instrument {
    Symbol symbol;                  // "600000.SH"
    std::string name;              // "浦发银行"
    Market market = Market::kSH;
    std::string market_name;       // human-friendly market label
    Board board = Board::kMain;
    SWIndustry industry = SWIndustry::kUnknown;
    Date list_date;                // 上市日期
    std::optional<Date> delist_date; // 退市日期 (if delisted)
    TradingStatus status = TradingStatus::kNormal;

    // Share capital
    int64_t total_shares = 0;      // 总股本
    int64_t float_shares = 0;      // 流通股本

    // For filtering
    bool is_tradable() const {
        return status == TradingStatus::kNormal;
    }

    bool is_st() const {
        return status == TradingStatus::kST || status == TradingStatus::kStarST;
    }

    // Days since listing
    int days_listed(Date today) const {
        return (today - list_date).count();
    }

    // Is it a new stock (< 120 trading days)?
    bool is_new_stock(Date today) const {
        return days_listed(today) < 120;
    }

    std::string market_label() const {
        return market_name.empty() ? market_name_from_enum(market) : market_name;
    }
};

} // namespace trade
