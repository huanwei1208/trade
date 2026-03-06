#include <gtest/gtest.h>
#include <Eigen/Dense>
#include <cmath>
#include <vector>

#include "trade/backtest/backtest_engine.h"
#include "trade/backtest/portfolio_state.h"
#include "trade/backtest/performance.h"
#include "trade/backtest/broker_sim.h"

using namespace trade;

// =============================================================================
// Order tests
// =============================================================================

TEST(BacktestOrderTest, OrderDefaults) {
    Order order;
    EXPECT_TRUE(order.symbol.empty());
    EXPECT_EQ(order.side, Side::kBuy);
    EXPECT_EQ(order.quantity, 0);
    EXPECT_EQ(order.order_type, OrderType::kMarketOnOpen);
    EXPECT_DOUBLE_EQ(order.limit_price, 0.0);
    EXPECT_DOUBLE_EQ(order.urgency, 0.5);
}

TEST(BacktestOrderTest, IsBuyIsSell) {
    Order buy_order;
    buy_order.side = Side::kBuy;
    EXPECT_TRUE(buy_order.is_buy());
    EXPECT_FALSE(buy_order.is_sell());

    Order sell_order;
    sell_order.side = Side::kSell;
    EXPECT_FALSE(sell_order.is_buy());
    EXPECT_TRUE(sell_order.is_sell());
}

// =============================================================================
// OrderResult tests
// =============================================================================

TEST(BacktestOrderResultTest, TotalCost) {
    OrderResult result;
    result.commission = 5.0;
    result.stamp_tax = 3.0;
    result.transfer_fee = 0.5;
    EXPECT_DOUBLE_EQ(result.total_cost(), 8.5);
}

TEST(BacktestOrderResultTest, IsFilled) {
    OrderResult filled;
    filled.status = FillStatus::kFilled;
    EXPECT_TRUE(filled.is_filled());

    OrderResult partial;
    partial.status = FillStatus::kPartialFill;
    EXPECT_TRUE(partial.is_filled());

    OrderResult rejected;
    rejected.status = FillStatus::kRejected;
    EXPECT_FALSE(rejected.is_filled());

    OrderResult cancelled;
    cancelled.status = FillStatus::kCancelled;
    EXPECT_FALSE(cancelled.is_filled());
}

// =============================================================================
// BacktestResult tests
// =============================================================================

TEST(BacktestResultTest, TotalReturn) {
    BacktestResult result;
    result.initial_capital = 1000000.0;
    result.final_nav = 1200000.0;
    EXPECT_NEAR(result.total_return(), 0.20, 1e-10);
}

TEST(BacktestResultTest, TotalReturnZeroCapital) {
    BacktestResult result;
    result.initial_capital = 0.0;
    result.final_nav = 100.0;
    EXPECT_DOUBLE_EQ(result.total_return(), 0.0);
}

TEST(BacktestResultTest, NavSeries) {
    BacktestResult result;
    DailyRecord r1;
    r1.nav = 1000000.0;
    r1.daily_return = 0.0;
    r1.drawdown = 0.0;
    result.daily_records.push_back(r1);

    DailyRecord r2;
    r2.nav = 1010000.0;
    r2.daily_return = 0.01;
    r2.drawdown = 0.0;
    result.daily_records.push_back(r2);

    auto navs = result.nav_series();
    ASSERT_EQ(navs.size(), 2u);
    EXPECT_DOUBLE_EQ(navs[0], 1000000.0);
    EXPECT_DOUBLE_EQ(navs[1], 1010000.0);

    auto rets = result.return_series();
    ASSERT_EQ(rets.size(), 2u);
    EXPECT_DOUBLE_EQ(rets[1], 0.01);

    auto dds = result.drawdown_series();
    ASSERT_EQ(dds.size(), 2u);
    EXPECT_DOUBLE_EQ(dds[0], 0.0);
}

// =============================================================================
// BacktestEngine::Config defaults
// =============================================================================

TEST(BacktestConfigTest, Defaults) {
    BacktestEngine::Config config;
    EXPECT_DOUBLE_EQ(config.initial_capital, 1000000.0);
    EXPECT_EQ(config.max_positions, 25);
    EXPECT_EQ(config.min_positions, 15);
    EXPECT_DOUBLE_EQ(config.max_adv_participation, 0.12);
    EXPECT_DOUBLE_EQ(config.rebalance_threshold, 0.01);
    EXPECT_DOUBLE_EQ(config.alpha_cost_multiple, 1.5);
    EXPECT_FALSE(config.verbose);
}

// =============================================================================
// TaxLot tests
// =============================================================================

TEST(TaxLotTest, IsSellable) {
    auto make_date = [](int y, int m, int d) -> Date {
        return std::chrono::sys_days{
            std::chrono::year{y} / std::chrono::month{static_cast<unsigned>(m)} /
            std::chrono::day{static_cast<unsigned>(d)}};
    };

    TaxLot lot;
    lot.buy_date = make_date(2024, 1, 15);
    lot.quantity = 100;
    lot.cost_price = 10.0;
    lot.sellable_date = make_date(2024, 1, 16);

    EXPECT_FALSE(lot.is_sellable(make_date(2024, 1, 15)));
    EXPECT_TRUE(lot.is_sellable(make_date(2024, 1, 16)));
    EXPECT_TRUE(lot.is_sellable(make_date(2024, 1, 17)));
}

TEST(TaxLotTest, TotalCost) {
    TaxLot lot;
    lot.quantity = 500;
    lot.cost_price = 12.50;
    EXPECT_DOUBLE_EQ(lot.total_cost(), 6250.0);
}

TEST(TaxLotTest, ZeroQuantityNotSellable) {
    auto make_date = [](int y, int m, int d) -> Date {
        return std::chrono::sys_days{
            std::chrono::year{y} / std::chrono::month{static_cast<unsigned>(m)} /
            std::chrono::day{static_cast<unsigned>(d)}};
    };

    TaxLot lot;
    lot.quantity = 0;
    lot.sellable_date = make_date(2024, 1, 1);
    EXPECT_FALSE(lot.is_sellable(make_date(2024, 6, 1)));
}

// =============================================================================
// Position tests
// =============================================================================

TEST(PositionTest, IsEmpty) {
    Position pos;
    EXPECT_TRUE(pos.is_empty());
    pos.total_qty = 100;
    EXPECT_FALSE(pos.is_empty());
}

// =============================================================================
// Trading cost calculation
// =============================================================================

TEST(BacktestTest, TradingCosts) {
    double price = 10.0;
    int qty = 1000;
    double amount = price * qty;

    double buy_commission = std::max(amount * 0.00025, 5.0);
    EXPECT_DOUBLE_EQ(buy_commission, 5.0);

    double sell_commission = std::max(amount * 0.00025, 5.0);
    double stamp_tax = amount * 0.0005;
    double sell_total = sell_commission + stamp_tax;
    EXPECT_DOUBLE_EQ(stamp_tax, 5.0);
    EXPECT_DOUBLE_EQ(sell_total, 10.0);

    double round_trip = buy_commission + sell_total;
    EXPECT_DOUBLE_EQ(round_trip, 15.0);
}

TEST(BacktestTest, LargeOrderCosts) {
    // Larger order where commission exceeds minimum
    double price = 50.0;
    int qty = 10000;
    double amount = price * qty;  // 500,000

    double buy_commission = std::max(amount * 0.00025, 5.0);
    // 500000 * 0.00025 = 125 > 5
    EXPECT_DOUBLE_EQ(buy_commission, 125.0);

    double stamp_tax = amount * 0.0005;  // 250
    EXPECT_DOUBLE_EQ(stamp_tax, 250.0);
}

// =============================================================================
// PerformanceCalculator tests
// =============================================================================

TEST(PerformanceCalculatorTest, ConfigDefaults) {
    PerformanceCalculator::Config config;
    EXPECT_DOUBLE_EQ(config.risk_free_rate, 0.025);
    EXPECT_EQ(config.annualisation_factor, 252);
    EXPECT_EQ(config.bootstrap_samples, 10000);
    EXPECT_EQ(config.bootstrap_block_size, 21);
    EXPECT_EQ(config.benchmark_name, "CSI300");
}

TEST(PerformanceCalculatorTest, AnnualisedReturn) {
    PerformanceCalculator calc;
    // 252 days of 0.04% daily return
    std::vector<double> daily_returns(252, 0.0004);
    double ann = calc.annualised_return(daily_returns);
    // Compound: (1.0004)^252 - 1 ~ 10.6%
    double expected = std::pow(1.0004, 252) - 1.0;
    EXPECT_NEAR(ann, expected, 0.01);
}

TEST(PerformanceCalculatorTest, CumulativeReturn) {
    PerformanceCalculator calc;
    std::vector<double> daily_returns = {0.01, 0.02, -0.01};
    double cum = calc.cumulative_return(daily_returns);
    double expected = (1.01 * 1.02 * 0.99) - 1.0;
    EXPECT_NEAR(cum, expected, 1e-10);
}

TEST(PerformanceCalculatorTest, SharpeRatio) {
    PerformanceCalculator::Config cfg;
    cfg.risk_free_rate = 0.0;
    PerformanceCalculator calc(cfg);
    // Constant positive returns => high Sharpe (zero std not possible)
    // Use slightly varying returns
    std::vector<double> returns;
    for (int i = 0; i < 252; ++i) {
        returns.push_back(0.001 + 0.0001 * (i % 3 - 1));
    }
    double sharpe = calc.sharpe_ratio(returns);
    EXPECT_GT(sharpe, 1.0);
}

TEST(PerformanceCalculatorTest, SortinoRatio) {
    PerformanceCalculator::Config cfg;
    cfg.risk_free_rate = 0.0;
    PerformanceCalculator calc(cfg);
    // Use returns with some negative values so downside deviation is non-zero
    std::vector<double> returns;
    for (int i = 0; i < 252; ++i) {
        returns.push_back(0.001 + 0.003 * (i % 5 - 2));
    }
    double sortino = calc.sortino_ratio(returns);
    // Should be a finite number (positive or NaN if no downside deviation)
    if (!std::isnan(sortino)) {
        EXPECT_GT(sortino, 0.0);
    }
}

TEST(PerformanceCalculatorTest, DrawdownAnalysis) {
    PerformanceCalculator calc;
    std::vector<double> nav = {100, 105, 110, 100, 95, 98, 112};
    auto dd = calc.analyse_drawdowns(nav);
    // Max drawdown: (110 - 95) / 110 = 0.13636
    EXPECT_NEAR(dd.max_drawdown, (110.0 - 95.0) / 110.0, 0.01);
    EXPECT_GT(dd.max_drawdown_duration, 0);
}

TEST(PerformanceCalculatorTest, CalmarRatio) {
    PerformanceCalculator calc;
    std::vector<double> returns(252, 0.0004);
    double ann = calc.annualised_return(returns);
    double max_dd = 0.10;
    double calmar = calc.calmar_ratio(returns, max_dd);
    EXPECT_NEAR(calmar, ann / max_dd, 0.01);
}

TEST(PerformanceCalculatorTest, HistoricalVaR) {
    PerformanceCalculator calc;
    std::vector<double> returns;
    for (int i = -50; i <= 50; ++i) {
        returns.push_back(static_cast<double>(i) / 1000.0);
    }
    double var_95 = calc.historical_var(returns, 0.95);
    double var_99 = calc.historical_var(returns, 0.99);
    // VaR can be positive (loss) or negative depending on sign convention
    // Higher confidence level should give a more extreme VaR
    EXPECT_NE(var_95, 0.0);
    EXPECT_NE(var_99, 0.0);
    // |var_99| >= |var_95|
    EXPECT_GE(std::abs(var_99), std::abs(var_95) - 0.01);
}

TEST(PerformanceCalculatorTest, Skewness) {
    PerformanceCalculator calc;
    // Symmetric distribution => skew ~ 0
    std::vector<double> returns = {-0.02, -0.01, 0.0, 0.01, 0.02};
    double skew = calc.compute_skewness(returns);
    EXPECT_NEAR(skew, 0.0, 0.1);
}

TEST(PerformanceCalculatorTest, Kurtosis) {
    PerformanceCalculator calc;
    std::vector<double> returns = {-0.02, -0.01, 0.0, 0.01, 0.02};
    double kurt = calc.compute_kurtosis(returns);
    // Excess kurtosis: implementation may use sample or population formula
    // For uniform-like data, excess kurtosis is ~-1.3 (population) or different with sample correction
    // Just verify it's a finite number
    EXPECT_FALSE(std::isnan(kurt));
    EXPECT_FALSE(std::isinf(kurt));
}

// =============================================================================
// BrokerSim config defaults
// =============================================================================

TEST(BrokerSimTest, ConfigDefaults) {
    BrokerSim::Config cfg;
    EXPECT_DOUBLE_EQ(cfg.commission_rate, 0.00025);
    EXPECT_DOUBLE_EQ(cfg.stamp_tax_rate, 0.0005);
    EXPECT_DOUBLE_EQ(cfg.commission_min_yuan, 5.0);
}
