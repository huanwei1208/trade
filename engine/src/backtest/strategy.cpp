#include "trade/backtest/strategy.h"

namespace trade {

// ---------------------------------------------------------------------------
// StrategyBase constructors
// ---------------------------------------------------------------------------

StrategyBase::StrategyBase() : strategy_config_{} {}
StrategyBase::StrategyBase(Config config) : strategy_config_(config) {}

} // namespace trade
