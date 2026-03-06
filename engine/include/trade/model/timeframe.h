#pragma once

#include <cstdint>

namespace trade {

enum class Timeframe : uint8_t {
    k1m = 0,
    k5m = 1,
    k15m = 2,
    k30m = 3,
    k60m = 4,
    kDaily = 5,
    kWeekly = 6,
};

} // namespace trade
