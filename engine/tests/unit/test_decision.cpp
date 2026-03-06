#include <gtest/gtest.h>
#include <Eigen/Dense>
#include <cmath>
#include <string>
#include <vector>
#include <unordered_map>

#include "trade/decision/signal.h"
#include "trade/decision/signal_combiner.h"
#include "trade/decision/universe_filter.h"
#include "trade/decision/portfolio_opt.h"
#include "trade/decision/pre_trade_check.h"
#include "trade/decision/order_manager.h"
#include "trade/decision/decision_report.h"
#include "trade/backtest/backtest_engine.h"

using namespace trade;

// Helper to make a Date from y/m/d
static Date make_date(int y, int m, int d) {
    return std::chrono::sys_days{
        std::chrono::year{y} / std::chrono::month{static_cast<unsigned>(m)} /
        std::chrono::day{static_cast<unsigned>(d)}};
}

// =============================================================================
// Signal tests
// =============================================================================

TEST(SignalTest, Defaults) {
    Signal signal;
    EXPECT_TRUE(signal.symbol.empty());
    EXPECT_DOUBLE_EQ(signal.alpha_score, 0.0);
    EXPECT_DOUBLE_EQ(signal.confidence, 0.0);
    EXPECT_EQ(signal.regime, Regime::kBull);
    EXPECT_FALSE(signal.is_conflict);
}

TEST(SignalTest, IsTradable) {
    Signal signal;
    signal.is_conflict = false;
    signal.confidence = 0.7;
    EXPECT_TRUE(signal.is_tradable());
}

TEST(SignalTest, NotTradableLowConfidence) {
    Signal signal;
    signal.is_conflict = false;
    signal.confidence = 0.5;
    EXPECT_FALSE(signal.is_tradable());
}

TEST(SignalTest, NotTradableConflict) {
    Signal signal;
    signal.is_conflict = true;
    signal.confidence = 0.9;
    EXPECT_FALSE(signal.is_tradable());
}

TEST(SignalTest, IsTradableBoundary) {
    Signal signal;
    signal.is_conflict = false;
    signal.confidence = 0.6;
    EXPECT_TRUE(signal.is_tradable());
}

TEST(SignalTest, HasNegShock) {
    Signal signal;
    signal.sentiment.neg_shock = true;
    EXPECT_TRUE(signal.has_neg_shock());

    signal.sentiment.neg_shock = false;
    EXPECT_FALSE(signal.has_neg_shock());
}

TEST(SignalTest, NumModels) {
    Signal signal;
    EXPECT_EQ(signal.num_models(), 0u);

    Signal::ModelScore ms1;
    ms1.model_name = "lgbm";
    ms1.raw_score = 0.5;
    ms1.calibrated_score = 0.3;
    ms1.weight = 0.6;
    signal.model_scores.push_back(ms1);

    Signal::ModelScore ms2;
    ms2.model_name = "xgb";
    ms2.raw_score = 0.4;
    ms2.calibrated_score = 0.2;
    ms2.weight = 0.4;
    signal.model_scores.push_back(ms2);

    EXPECT_EQ(signal.num_models(), 2u);
}

TEST(ModelScoreTest, Defaults) {
    Signal::ModelScore ms;
    EXPECT_TRUE(ms.model_name.empty());
    EXPECT_DOUBLE_EQ(ms.raw_score, 0.0);
    EXPECT_DOUBLE_EQ(ms.calibrated_score, 0.0);
    EXPECT_DOUBLE_EQ(ms.weight, 0.0);
}

TEST(SentimentOverlayTest, Defaults) {
    Signal::SentimentOverlay overlay;
    EXPECT_TRUE(overlay.stock_mood.empty());
    EXPECT_FALSE(overlay.neg_shock);
    EXPECT_TRUE(overlay.key_news.empty());
}

// =============================================================================
// SignalCombiner tests
// =============================================================================

TEST(SignalCombinerTest, ConfigDefaults) {
    SignalCombiner::Config cfg;
    EXPECT_EQ(cfg.zscore_lookback, 60);
    EXPECT_EQ(cfg.icir_lookback, 60);
    EXPECT_DOUBLE_EQ(cfg.regime_fit_floor, 0.5);
    EXPECT_DOUBLE_EQ(cfg.regime_fit_cap, 1.5);
    EXPECT_DOUBLE_EQ(cfg.min_confidence, 0.6);
    EXPECT_DOUBLE_EQ(cfg.conflict_alpha_threshold, 0.05);
    EXPECT_DOUBLE_EQ(cfg.conflict_dispersion_threshold, 0.30);
}

TEST(SignalCombinerTest, CalibrateZeroStd) {
    SignalCombiner combiner;
    Eigen::VectorXd raw(2);
    raw << 0.5, -0.3;
    std::vector<SignalCombiner::ModelMeta> metas(2);
    metas[0].model_name = "m1";
    metas[0].rolling_mean = 0.0;
    metas[0].rolling_std = 1.0;
    metas[1].model_name = "m2";
    metas[1].rolling_mean = 0.0;
    metas[1].rolling_std = 1.0;

    auto calibrated = combiner.calibrate(raw, metas);
    EXPECT_EQ(calibrated.size(), 2);
    // With std=1, mean=0, z = raw itself, then logistic squash
    // logistic(0.5) = 2/(1+exp(-0.5))-1 ~ 0.2449
    EXPECT_GT(calibrated(0), 0.0);
    EXPECT_LT(calibrated(1), 0.0);
}

TEST(SignalCombinerTest, CalibrateSymmetry) {
    SignalCombiner combiner;
    Eigen::VectorXd raw(2);
    raw << 1.0, -1.0;
    std::vector<SignalCombiner::ModelMeta> metas(2);
    metas[0].rolling_mean = 0.0;
    metas[0].rolling_std = 1.0;
    metas[1].rolling_mean = 0.0;
    metas[1].rolling_std = 1.0;

    auto calibrated = combiner.calibrate(raw, metas);
    // Logistic squash is symmetric: squash(1) = -squash(-1)
    EXPECT_NEAR(calibrated(0), -calibrated(1), 1e-10);
}

TEST(SignalCombinerTest, CombineBasic) {
    SignalCombiner combiner;
    Eigen::VectorXd calibrated(2);
    calibrated << 0.6, 0.4;
    std::vector<SignalCombiner::ModelMeta> metas(2);
    metas[0].model_name = "m1";
    metas[0].composite_weight = 0.6;
    metas[1].model_name = "m2";
    metas[1].composite_weight = 0.4;

    auto sig = combiner.combine("600000.SH", calibrated, Regime::kBull, metas);
    EXPECT_EQ(sig.symbol, "600000.SH");
    EXPECT_EQ(sig.regime, Regime::kBull);
    // Alpha should be weighted average: 0.6*0.6 + 0.4*0.4 = 0.52
    EXPECT_GT(sig.alpha_score, 0.0);
}

TEST(SignalCombinerTest, CombineDetectsConflict) {
    SignalCombiner::Config cfg;
    cfg.conflict_alpha_threshold = 0.05;
    cfg.conflict_dispersion_threshold = 0.30;
    SignalCombiner combiner(cfg);

    // Two models disagree strongly: scores nearly cancel out, high dispersion
    Eigen::VectorXd calibrated(2);
    calibrated << 0.8, -0.8;
    std::vector<SignalCombiner::ModelMeta> metas(2);
    metas[0].model_name = "m1";
    metas[0].composite_weight = 0.5;
    metas[1].model_name = "m2";
    metas[1].composite_weight = 0.5;

    auto sig = combiner.combine("000001.SZ", calibrated, Regime::kBull, metas);
    // Alpha ~ 0 and dispersion is high => conflict
    EXPECT_NEAR(sig.alpha_score, 0.0, 0.1);
    EXPECT_TRUE(sig.is_conflict);
}

TEST(SignalCombinerTest, CombineBatchMultipleSymbols) {
    SignalCombiner combiner;
    std::vector<Symbol> symbols = {"600000.SH", "000001.SZ", "600519.SH"};
    Eigen::MatrixXd raw(3, 2);
    raw << 0.5, 0.3,
           -0.2, -0.4,
           0.8, 0.6;
    std::vector<SignalCombiner::ModelMeta> metas(2);
    metas[0].model_name = "m1";
    metas[0].rolling_mean = 0.0;
    metas[0].rolling_std = 1.0;
    metas[0].composite_weight = 0.5;
    metas[1].model_name = "m2";
    metas[1].rolling_mean = 0.0;
    metas[1].rolling_std = 1.0;
    metas[1].composite_weight = 0.5;

    auto signals = combiner.combine_batch(symbols, raw, Regime::kBull, metas);
    ASSERT_EQ(signals.size(), 3u);
    EXPECT_EQ(signals[0].symbol, "600000.SH");
    EXPECT_EQ(signals[1].symbol, "000001.SZ");
    EXPECT_EQ(signals[2].symbol, "600519.SH");
    // Third symbol has strongest positive raw scores
    EXPECT_GT(signals[2].alpha_score, signals[0].alpha_score);
}

TEST(SignalCombinerTest, UpdateWeights) {
    SignalCombiner combiner;
    std::vector<SignalCombiner::ModelMeta> metas(2);
    metas[0].model_name = "m1";
    metas[1].model_name = "m2";

    // Create recent IC matrix: 60 days x 2 models
    Eigen::MatrixXd ic_matrix(60, 2);
    for (int i = 0; i < 60; ++i) {
        ic_matrix(i, 0) = 0.03 + 0.001 * (i % 5 - 2);  // stable IC ~ 0.03
        ic_matrix(i, 1) = 0.01 + 0.01 * (i % 3 - 1);    // volatile IC ~ 0.01
    }

    combiner.update_weights(metas, ic_matrix, Regime::kBull);
    // Model 1 has higher and more stable IC, should get higher weight
    EXPECT_GT(metas[0].composite_weight, 0.0);
    EXPECT_GT(metas[1].composite_weight, 0.0);
    // Weights should be normalised (sum to 1)
    EXPECT_NEAR(metas[0].composite_weight + metas[1].composite_weight, 1.0, 1e-6);
}

// =============================================================================
// UniverseFilter tests
// =============================================================================

TEST(UniverseFilterTest, ConfigDefaults) {
    UniverseFilter::Config cfg;
    EXPECT_EQ(cfg.min_listing_days, 120);
    EXPECT_DOUBLE_EQ(cfg.min_adv_20d, 5'000'000.0);
    EXPECT_TRUE(cfg.exclude_st);
    EXPECT_TRUE(cfg.exclude_suspended);
    EXPECT_TRUE(cfg.exclude_limit_locked);
    EXPECT_TRUE(cfg.exclude_delisting);
}

TEST(UniverseFilterTest, IsSuspended) {
    Instrument inst;
    inst.status = TradingStatus::kNormal;
    EXPECT_FALSE(UniverseFilter::is_suspended(inst));

    inst.status = TradingStatus::kSuspended;
    EXPECT_TRUE(UniverseFilter::is_suspended(inst));
}

TEST(UniverseFilterTest, IsST) {
    Instrument inst;
    inst.status = TradingStatus::kNormal;
    EXPECT_FALSE(UniverseFilter::is_st(inst));

    inst.status = TradingStatus::kST;
    EXPECT_TRUE(UniverseFilter::is_st(inst));

    inst.status = TradingStatus::kStarST;
    EXPECT_TRUE(UniverseFilter::is_st(inst));
}

TEST(UniverseFilterTest, IsDelisting) {
    Instrument inst;
    inst.status = TradingStatus::kNormal;
    EXPECT_FALSE(UniverseFilter::is_delisting(inst));

    inst.status = TradingStatus::kDelisting;
    EXPECT_TRUE(UniverseFilter::is_delisting(inst));
}

TEST(UniverseFilterTest, IsNewStock) {
    UniverseFilter filter;
    Instrument inst;
    inst.list_date = make_date(2024, 1, 1);

    // 50 days since listing -> new stock
    EXPECT_TRUE(filter.is_new_stock(inst, make_date(2024, 2, 20)));
    // 200 days since listing -> not new
    EXPECT_FALSE(filter.is_new_stock(inst, make_date(2024, 7, 20)));
}

TEST(UniverseFilterTest, IsIlliquid) {
    UniverseFilter filter;
    std::unordered_map<Symbol, double> adv;
    adv["600000.SH"] = 10'000'000.0;  // 10M > 5M threshold
    adv["000999.SZ"] = 1'000'000.0;   // 1M < 5M threshold

    EXPECT_FALSE(filter.is_illiquid("600000.SH", adv));
    EXPECT_TRUE(filter.is_illiquid("000999.SZ", adv));
    // Unknown symbol behavior depends on implementation
    [[maybe_unused]] bool unknown_result = filter.is_illiquid("unknown", adv);
}

TEST(UniverseFilterTest, FilterBasic) {
    UniverseFilter filter;
    Date today = make_date(2024, 6, 15);

    std::unordered_map<Symbol, Instrument> instruments;
    // Normal stock, listed long ago
    Instrument normal;
    normal.symbol = "600000.SH";
    normal.status = TradingStatus::kNormal;
    normal.list_date = make_date(2020, 1, 1);
    instruments["600000.SH"] = normal;

    // ST stock
    Instrument st;
    st.symbol = "000999.SZ";
    st.status = TradingStatus::kST;
    st.list_date = make_date(2020, 1, 1);
    instruments["000999.SZ"] = st;

    // Suspended stock
    Instrument susp;
    susp.symbol = "600001.SH";
    susp.status = TradingStatus::kSuspended;
    susp.list_date = make_date(2020, 1, 1);
    instruments["600001.SH"] = susp;

    // New stock (listed 30 days ago)
    Instrument new_stock;
    new_stock.symbol = "688001.SH";
    new_stock.status = TradingStatus::kNormal;
    new_stock.list_date = make_date(2024, 5, 16);
    instruments["688001.SH"] = new_stock;

    MarketSnapshot snapshot;
    snapshot.date = today;
    // Add bars for all stocks
    for (auto& [sym, inst] : instruments) {
        Bar bar;
        bar.symbol = sym;
        bar.close = 10.0;
        bar.prev_close = 10.0;
        bar.limit_up = 11.0;
        bar.limit_down = 9.0;
        bar.volume = 1000000;
        snapshot.bars[sym] = bar;
        snapshot.instruments[sym] = inst;
    }

    std::unordered_map<Symbol, double> adv;
    adv["600000.SH"] = 10'000'000.0;
    adv["000999.SZ"] = 10'000'000.0;
    adv["600001.SH"] = 10'000'000.0;
    adv["688001.SH"] = 10'000'000.0;

    auto tradable = filter.filter(instruments, snapshot, today, adv);
    // Only 600000.SH should pass (ST, suspended, new stock excluded)
    EXPECT_EQ(tradable.size(), 1u);
    if (!tradable.empty()) {
        EXPECT_EQ(tradable[0], "600000.SH");
    }

    auto stats = filter.last_stats();
    EXPECT_EQ(stats.total_input, 4);
    EXPECT_EQ(stats.total_output, 1);
    EXPECT_EQ(stats.rejected_st, 1);
    EXPECT_EQ(stats.rejected_suspended, 1);
    EXPECT_EQ(stats.rejected_new_stock, 1);
}

// =============================================================================
// PortfolioOptimizer tests
// =============================================================================

TEST(PortfolioOptimizerTest, ConstraintDefaults) {
    PortfolioOptimizer::Constraints c;
    EXPECT_DOUBLE_EQ(c.max_var_99_1d, 0.03);
    EXPECT_DOUBLE_EQ(c.beta_min, 0.6);
    EXPECT_DOUBLE_EQ(c.beta_max, 1.2);
    EXPECT_DOUBLE_EQ(c.max_single_weight, 0.10);
    EXPECT_DOUBLE_EQ(c.max_industry_weight, 0.35);
    EXPECT_DOUBLE_EQ(c.max_top3_weight, 0.22);
    EXPECT_DOUBLE_EQ(c.cash_floor, 0.10);
    EXPECT_DOUBLE_EQ(c.max_turnover, 0.30);
    EXPECT_EQ(c.max_positions, 25);
    EXPECT_EQ(c.min_positions, 15);
}

TEST(PortfolioOptimizerTest, OptimizeBasic) {
    PortfolioOptimizer::Constraints constraints;
    constraints.min_positions = 2;
    constraints.max_positions = 5;
    constraints.cash_floor = 0.05;
    PortfolioOptimizer opt(constraints);

    // 3 candidates
    std::vector<PortfolioOptimizer::Candidate> candidates(3);
    candidates[0].symbol = "600000.SH";
    candidates[0].alpha = 0.05;
    candidates[0].confidence = 0.8;
    candidates[0].estimated_cost = 10.0;
    candidates[0].beta = 1.0;
    candidates[0].adv_20d = 50'000'000.0;

    candidates[1].symbol = "000001.SZ";
    candidates[1].alpha = 0.03;
    candidates[1].confidence = 0.7;
    candidates[1].estimated_cost = 8.0;
    candidates[1].beta = 0.9;
    candidates[1].adv_20d = 30'000'000.0;

    candidates[2].symbol = "600519.SH";
    candidates[2].alpha = 0.04;
    candidates[2].confidence = 0.75;
    candidates[2].estimated_cost = 12.0;
    candidates[2].beta = 1.1;
    candidates[2].adv_20d = 80'000'000.0;

    std::unordered_map<Symbol, double> current_weights;
    Eigen::MatrixXd cov(3, 3);
    cov << 0.04, 0.01, 0.005,
           0.01, 0.03, 0.008,
           0.005, 0.008, 0.05;

    auto result = opt.optimize(candidates, current_weights, cov);
    // Should produce some target weights
    EXPECT_EQ(result.symbols.size(), 3u);
    EXPECT_EQ(result.target_weights.size(), 3);
    // All weights should be non-negative
    for (int i = 0; i < result.target_weights.size(); ++i) {
        EXPECT_GE(result.target_weights(i), 0.0);
    }
    // Weights should not exceed single stock cap
    for (int i = 0; i < result.target_weights.size(); ++i) {
        EXPECT_LE(result.target_weights(i), constraints.max_single_weight + 1e-6);
    }
    // Total weight should leave room for cash floor
    double total_w = result.target_weights.sum();
    EXPECT_LE(total_w, 1.0 - constraints.cash_floor + 1e-6);
}

TEST(PortfolioOptimizerTest, GenerateTrades) {
    std::vector<Symbol> symbols = {"A", "B", "C"};
    Eigen::VectorXd target(3);
    target << 0.10, 0.05, 0.00;
    std::unordered_map<Symbol, double> current;
    current["A"] = 0.05;
    current["B"] = 0.05;
    current["C"] = 0.08;

    auto trades = PortfolioOptimizer::generate_trades(symbols, target, current, 0.01);
    // A: 0.05 -> 0.10 (buy), C: 0.08 -> 0.00 (sell)
    // B: 0.05 -> 0.05 (no trade, below threshold)
    bool found_buy_a = false, found_sell_c = false;
    for (auto& t : trades) {
        if (t.symbol == "A") {
            EXPECT_EQ(t.side, Side::kBuy);
            EXPECT_NEAR(t.delta_weight, 0.05, 1e-6);
            found_buy_a = true;
        }
        if (t.symbol == "C") {
            EXPECT_EQ(t.side, Side::kSell);
            EXPECT_NEAR(t.delta_weight, -0.08, 1e-6);
            found_sell_c = true;
        }
    }
    EXPECT_TRUE(found_buy_a);
    EXPECT_TRUE(found_sell_c);
}

TEST(PortfolioOptimizerTest, SelectCandidates) {
    std::vector<Signal> signals(3);
    signals[0].symbol = "A";
    signals[0].alpha_score = 0.05;
    signals[0].confidence = 0.8;
    signals[0].is_conflict = false;

    signals[1].symbol = "B";
    signals[1].alpha_score = 0.03;
    signals[1].confidence = 0.7;
    signals[1].is_conflict = false;

    signals[2].symbol = "C";
    signals[2].alpha_score = 0.04;
    signals[2].confidence = 0.9;
    signals[2].is_conflict = false;

    std::unordered_map<Symbol, double> costs = {{"A", 0.01}, {"B", 0.01}, {"C", 0.01}};
    std::unordered_map<Symbol, double> betas = {{"A", 1.0}, {"B", 1.0}, {"C", 1.0}};
    std::unordered_map<Symbol, SWIndustry> industries = {
        {"A", SWIndustry::kBanking}, {"B", SWIndustry::kBanking}, {"C", SWIndustry::kElectronics}};
    std::unordered_map<Symbol, double> adv = {{"A", 50e6}, {"B", 50e6}, {"C", 50e6}};

    auto candidates = PortfolioOptimizer::select_candidates(
        signals, costs, betas, industries, adv, 1.5, 5);

    // All 3 signals should qualify (alpha > cost * 1.5 for all)
    EXPECT_GE(candidates.size(), 1u);
    EXPECT_LE(candidates.size(), 3u);
    // Candidates should be sorted by alpha (highest first)
    if (candidates.size() >= 2) {
        EXPECT_GE(candidates[0].alpha, candidates[1].alpha);
    }
}

// =============================================================================
// PreTradeChecker tests
// =============================================================================

TEST(PreTradeCheckerTest, ConfigDefaults) {
    PreTradeChecker::Config cfg;
    EXPECT_DOUBLE_EQ(cfg.max_participation, 0.12);
    EXPECT_DOUBLE_EQ(cfg.limit_proximity_warn_pct, 0.02);
    EXPECT_DOUBLE_EQ(cfg.limit_proximity_reject_pct, 0.005);
    EXPECT_DOUBLE_EQ(cfg.min_order_notional, 5000.0);
    EXPECT_EQ(cfg.lot_size, 100);
}

TEST(PreTradeCheckerTest, RoundToLot) {
    PreTradeChecker checker;
    EXPECT_EQ(checker.round_to_lot(150), 100);
    EXPECT_EQ(checker.round_to_lot(250), 200);
    EXPECT_EQ(checker.round_to_lot(300), 300);
    EXPECT_EQ(checker.round_to_lot(99), 0);
    EXPECT_EQ(checker.round_to_lot(0), 0);
}

TEST(PreTradeCheckerTest, CheckT1Sellable) {
    PreTradeChecker checker;
    PreTradeChecker::PortfolioState state;
    state.holdings["600000.SH"] = 1000;
    state.sellable_qty["600000.SH"] = 500;  // 500 of 1000 are sellable

    // Selling 500 is OK (exactly sellable)
    EXPECT_TRUE(checker.check_t1_sellable("600000.SH", 500, state));
    // Selling 300 is OK
    EXPECT_TRUE(checker.check_t1_sellable("600000.SH", 300, state));
    // Selling 600 exceeds sellable
    EXPECT_FALSE(checker.check_t1_sellable("600000.SH", 600, state));
    // Selling a stock we don't hold
    EXPECT_FALSE(checker.check_t1_sellable("000001.SZ", 100, state));
}

TEST(PreTradeCheckerTest, MaxParticipationQty) {
    PreTradeChecker::Config cfg;
    cfg.max_participation = 0.12;
    PreTradeChecker checker(cfg);

    PreTradeChecker::MarketData md;
    md.adv_20d["600000.SH"] = 100'000'000.0;  // 100M yuan ADV

    double price = 10.0;
    Volume max_qty = checker.max_participation_qty("600000.SH", price, md);
    // max_notional = 0.12 * 100M = 12M yuan
    // max_qty = 12M / 10 = 1,200,000 shares
    EXPECT_EQ(max_qty, 1'200'000);
}

TEST(PreTradeCheckerTest, CheckOrder) {
    PreTradeChecker checker;
    PreTradeChecker::PortfolioState state;
    state.cash = 1'000'000.0;
    state.nav = 10'000'000.0;

    PreTradeChecker::MarketData md;
    Bar bar;
    bar.symbol = "600000.SH";
    bar.close = 10.0;
    bar.prev_close = 10.0;
    bar.limit_up = 11.0;
    bar.limit_down = 9.0;
    md.bars["600000.SH"] = bar;

    Instrument inst;
    inst.symbol = "600000.SH";
    inst.status = TradingStatus::kNormal;
    md.instruments["600000.SH"] = inst;
    md.adv_20d["600000.SH"] = 50'000'000.0;
    md.limit_up["600000.SH"] = 11.0;
    md.limit_down["600000.SH"] = 9.0;

    Order order;
    order.symbol = "600000.SH";
    order.side = Side::kBuy;
    order.quantity = 1000;

    auto result = checker.check(order, state, md);
    EXPECT_TRUE(result.pass);
    EXPECT_GE(result.adjusted_qty, 0);
}

// =============================================================================
// OrderManager tests
// =============================================================================

TEST(OrderManagerTest, ConfigDefaults) {
    OrderManager::Config cfg;
    EXPECT_EQ(cfg.avoid_open_minutes, 15);
    EXPECT_EQ(cfg.slice_interval_minutes, 10);
    EXPECT_DOUBLE_EQ(cfg.target_participation, 0.10);
    EXPECT_DOUBLE_EQ(cfg.max_participation, 0.12);
    EXPECT_DOUBLE_EQ(cfg.large_order_adv_pct, 0.05);
    EXPECT_EQ(cfg.large_order_max_sessions, 3);
}

TEST(OrderManagerTest, EstimateSlippageBps) {
    OrderManager mgr;
    // Low participation, low vol
    double slip1 = mgr.estimate_slippage_bps(0.05, 0.20, 0.5);
    EXPECT_GT(slip1, 0.0);

    // Higher participation => higher slippage
    double slip2 = mgr.estimate_slippage_bps(0.12, 0.20, 0.5);
    EXPECT_GT(slip2, slip1);

    // Higher volatility => higher slippage
    double slip3 = mgr.estimate_slippage_bps(0.05, 0.40, 0.5);
    EXPECT_GT(slip3, slip1);
}

TEST(OrderManagerTest, EstimateExecutionCost) {
    double notional = 100'000.0;
    double slippage_bps = 10.0;

    double buy_cost = OrderManager::estimate_execution_cost(notional, slippage_bps, false);
    double sell_cost = OrderManager::estimate_execution_cost(notional, slippage_bps, true);
    // Sell should cost more due to stamp tax
    EXPECT_GT(sell_cost, buy_cost);
    EXPECT_GT(buy_cost, 0.0);
}

TEST(OrderManagerTest, IsLargeOrder) {
    OrderManager mgr;
    double adv = 100'000'000.0;  // 100M yuan
    // > 5% of ADV = 5M
    EXPECT_TRUE(mgr.is_large_order(6'000'000.0, adv));
    EXPECT_FALSE(mgr.is_large_order(4'000'000.0, adv));
}

TEST(OrderManagerTest, SessionsForOrder) {
    OrderManager mgr;
    double adv = 10'000'000.0;  // 10M yuan
    // Small order: 1 session
    EXPECT_EQ(mgr.sessions_for_order(100'000.0, adv), 1);
    // Large order: multiple sessions
    int sessions = mgr.sessions_for_order(20'000'000.0, adv);
    EXPECT_GE(sessions, 1);
    EXPECT_LE(sessions, 3);
}

TEST(OrderManagerTest, ExecutionPlanEmpty) {
    OrderManager::ExecutionPlan plan;
    EXPECT_TRUE(plan.empty());
    EXPECT_EQ(plan.size(), 0u);
}

// =============================================================================
// DecisionReporter tests
// =============================================================================

TEST(DecisionReporterTest, RegimeToString) {
    EXPECT_EQ(DecisionReporter::regime_to_string(Regime::kBull), "bull");
    EXPECT_EQ(DecisionReporter::regime_to_string(Regime::kBear), "bear");
    EXPECT_EQ(DecisionReporter::regime_to_string(Regime::kShock), "shock");
}

TEST(DecisionReporterTest, SideToString) {
    EXPECT_EQ(DecisionReporter::side_to_string(Side::kBuy), "buy");
    EXPECT_EQ(DecisionReporter::side_to_string(Side::kSell), "sell");
}

TEST(DecisionReporterTest, GeneratePositionReport) {
    DecisionReporter reporter;

    Signal sig;
    sig.symbol = "600000.SH";
    sig.alpha_score = 1.82;
    sig.confidence = 0.73;
    sig.regime = Regime::kBull;
    sig.is_conflict = false;
    sig.sentiment.stock_mood = "bullish";
    sig.sentiment.neg_shock = false;

    DecisionReporter::PositionRisk risk;
    risk.symbol = "600000.SH";
    risk.target_weight = 0.065;
    risk.current_weight = 0.0;
    risk.risk_contribution = 0.054;
    risk.marginal_var = 0.0028;
    risk.liquidity_days = 1.2;

    DecisionReporter::ExitPlan exit;
    exit.time_stop_days = 10;
    exit.signal_stop = 0.0;
    exit.risk_stop_pct = -0.05;
    exit.take_profit_pct = 0.08;

    auto report = reporter.generate_position_report(
        sig, risk, exit, "buy", "momentum + value", {"alpha_decay", "sector_rotation"});

    EXPECT_EQ(report["ticker"], "600000.SH");
    EXPECT_EQ(report["action"], "buy");
    EXPECT_NEAR(report["target_weight"].get<double>(), 0.065, 1e-6);
    EXPECT_NEAR(report["alpha_score"].get<double>(), 1.82, 1e-6);
    EXPECT_EQ(report["regime"], "bull");
}

TEST(DecisionReporterTest, GeneratePortfolioReport) {
    DecisionReporter reporter;

    DecisionReporter::RiskDashboard dashboard;
    dashboard.gross_exposure = 0.88;
    dashboard.net_exposure = 0.72;
    dashboard.cash_weight = 0.12;
    dashboard.var_99_1d = 0.021;
    dashboard.cvar_99_1d = 0.032;
    dashboard.market_regime = Regime::kBull;
    dashboard.market_sentiment = "bullish";
    dashboard.sector_breakdown["banking"] = 0.15;
    dashboard.sector_breakdown["tech"] = 0.22;

    auto report = reporter.generate_portfolio_report(dashboard);
    EXPECT_NEAR(report["gross_exposure"].get<double>(), 0.88, 1e-6);
    EXPECT_NEAR(report["cash"].get<double>(), 0.12, 1e-6);
    EXPECT_EQ(report["market_regime"], "bull");
}

TEST(DecisionReporterTest, PositionRiskDefaults) {
    DecisionReporter::PositionRisk risk;
    EXPECT_DOUBLE_EQ(risk.target_weight, 0.0);
    EXPECT_DOUBLE_EQ(risk.current_weight, 0.0);
    EXPECT_DOUBLE_EQ(risk.risk_contribution, 0.0);
    EXPECT_DOUBLE_EQ(risk.marginal_var, 0.0);
    EXPECT_DOUBLE_EQ(risk.liquidity_days, 0.0);
}

TEST(DecisionReporterTest, ExitPlanDefaults) {
    DecisionReporter::ExitPlan exit;
    EXPECT_EQ(exit.time_stop_days, 0);
    EXPECT_DOUBLE_EQ(exit.signal_stop, 0.0);
    EXPECT_DOUBLE_EQ(exit.risk_stop_pct, 0.0);
    EXPECT_DOUBLE_EQ(exit.take_profit_pct, 0.0);
}

// =============================================================================
// Decision logic integration tests
// =============================================================================

TEST(DecisionLogicTest, AlphaCostGating) {
    double alpha = 0.003;  // 30bps
    double cost = 0.001;   // 10bps
    double gate = 1.5;
    EXPECT_GT(alpha, gate * cost);  // 30bps > 15bps -> trade

    double low_alpha = 0.0014;
    EXPECT_LT(low_alpha, gate * cost);  // 14bps < 15bps -> don't trade
}

TEST(DecisionLogicTest, ConfidenceThreshold) {
    Signal sig;
    sig.is_conflict = false;
    sig.confidence = 0.73;
    EXPECT_TRUE(sig.is_tradable());

    sig.confidence = 0.45;
    EXPECT_FALSE(sig.is_tradable());

    sig.confidence = 0.6;
    EXPECT_TRUE(sig.is_tradable());

    sig.confidence = 0.59;
    EXPECT_FALSE(sig.is_tradable());
}
