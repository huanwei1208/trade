#pragma once

#include "trade/common/types.h"

#include <optional>
#include <string>
#include <vector>

namespace trade {

// Securities account identity and provider auth payload.
struct BrokerAccount {
    std::string account_id;
    std::string broker;
    std::string account_name;
    std::string auth_payload;  // JSON/plain payload from broker openapi
    bool is_active = true;
};

// End-of-day account cash snapshot.
struct AccountCashSnapshot {
    std::string account_id;
    Date as_of_date{};
    double total_asset = 0.0;
    double cash = 0.0;
    double available_cash = 0.0;
    double frozen_cash = 0.0;
    double market_value = 0.0;
};

// End-of-day position snapshot for one symbol.
struct AccountPositionSnapshot {
    std::string account_id;
    Date as_of_date{};
    Symbol symbol;
    int64_t quantity = 0;
    int64_t available_quantity = 0;
    double cost_price = 0.0;
    double last_price = 0.0;
    double market_value = 0.0;
    double unrealized_pnl = 0.0;
    double unrealized_pnl_ratio = 0.0;
};

// Trade execution record.
struct AccountTradeRecord {
    std::string account_id;
    std::string trade_id;
    Date trade_date{};
    Symbol symbol;
    Side side = Side::kBuy;
    double price = 0.0;
    int64_t quantity = 0;
    double amount = 0.0;
    double fee = 0.0;
};

// Combined broker snapshot payload.
struct AccountSnapshot {
    BrokerAccount account;
    std::optional<AccountCashSnapshot> cash;
    std::vector<AccountPositionSnapshot> positions;
    std::vector<AccountTradeRecord> trades;
};

} // namespace trade

