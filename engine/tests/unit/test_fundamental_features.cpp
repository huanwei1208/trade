#include <gtest/gtest.h>
#include "trade/model/financial_report.h"
#include <vector>
#include <cmath>

using namespace trade;

// Helper to make a report
static FinancialReport make_report(int year, int q, double roe,
                                    double net_profit, double op_cf) {
    FinancialReport r;
    r.symbol = "600000.SH";
    if (q == 1)      r.report_date = std::chrono::sys_days{std::chrono::year{year}/3/31};
    else if (q == 2) r.report_date = std::chrono::sys_days{std::chrono::year{year}/6/30};
    else if (q == 3) r.report_date = std::chrono::sys_days{std::chrono::year{year}/9/30};
    else             r.report_date = std::chrono::sys_days{std::chrono::year{year}/12/31};
    r.publish_date = r.report_date;
    r.roe = roe;
    r.net_profit = net_profit;
    r.op_cash_flow = op_cf;
    r.revenue = net_profit * 5.0;
    r.total_equity = net_profit / (roe / 100.0 + 1e-10);
    r.total_assets = r.total_equity * 2.0;
    r.eps = net_profit / 1e9;
    r.bps = r.total_equity / 1e9;
    return r;
}

TEST(FundamentalSignal, EmptyHistoryReturnsDefault) {
    FundamentalSignal sig = compute_fundamental_signal({}, 10.0, 1000000000LL);
    EXPECT_EQ(sig.quarters_available, 0);
    EXPECT_FLOAT_EQ(sig.roe_ttm, 0.0f);
}

TEST(FundamentalSignal, ROETTMIsAverageOfLastFourQuarters) {
    // 4 quarters with roe = 10, 12, 14, 16 -> avg = 13
    std::vector<FinancialReport> hist = {
        make_report(2023, 1, 10, 1e9, 1.2e9),
        make_report(2023, 2, 12, 1.1e9, 1.3e9),
        make_report(2023, 3, 14, 1.2e9, 1.4e9),
        make_report(2023, 4, 16, 1.3e9, 1.5e9),
    };
    FundamentalSignal sig = compute_fundamental_signal(hist, 10.0, 1000000000LL);
    EXPECT_NEAR(sig.roe_ttm, 13.0f, 0.5f);
    EXPECT_EQ(sig.quarters_available, 4);
}

TEST(FundamentalSignal, CashFlowQualityAboveOneForHighQuality) {
    // op_cash_flow > net_profit -> quality > 1
    std::vector<FinancialReport> hist = {
        make_report(2023, 1, 15, 1e9, 1.5e9),
        make_report(2023, 2, 15, 1.1e9, 1.6e9),
        make_report(2023, 3, 15, 1.2e9, 1.7e9),
        make_report(2023, 4, 15, 1.3e9, 1.8e9),
    };
    FundamentalSignal sig = compute_fundamental_signal(hist, 10.0, 1000000000LL);
    EXPECT_GT(sig.cash_flow_quality, 1.0f);
}

TEST(FundamentalSignal, PBFromBPS) {
    FinancialReport r = make_report(2023, 4, 15, 1e9, 1.2e9);
    r.bps = 8.0;
    FundamentalSignal sig = compute_fundamental_signal({r}, 10.0, 1000000000LL);
    // pb = price / bps = 10.0 / 8.0 = 1.25
    EXPECT_NEAR(sig.pb, 1.25f, 0.01f);
}

TEST(FundamentalSignal, RoeMomentumPositiveWhenImproving) {
    // 8 quarters: first 4 at ROE=10, next 4 at ROE=15 -> momentum > 0
    std::vector<FinancialReport> hist;
    for (int q = 1; q <= 4; ++q)
        hist.push_back(make_report(2022, q, 10, 1e9, 1.1e9));
    for (int q = 1; q <= 4; ++q)
        hist.push_back(make_report(2023, q, 15, 1.5e9, 1.7e9));
    FundamentalSignal sig = compute_fundamental_signal(hist, 10.0, 1000000000LL);
    EXPECT_GT(sig.roe_momentum, 0.0f);
}

TEST(FundamentalSignal, PEPercentileInRange) {
    // 12 quarters with varying profits -> pe_percentile in [0,1]
    std::vector<FinancialReport> hist;
    for (int i = 0; i < 12; ++i)
        hist.push_back(make_report(2021 + i/4, (i%4)+1, 12.0,
                                    (1.0 + i*0.05)*1e9, 1.2e9));
    FundamentalSignal sig = compute_fundamental_signal(hist, 20.0, 2000000000LL);
    EXPECT_GE(sig.pe_percentile, 0.0f);
    EXPECT_LE(sig.pe_percentile, 1.0f);
}

TEST(FundamentalSignal, SingleQuarterStillComputes) {
    // Only one quarter should still compute roe_ttm and pb
    FinancialReport r = make_report(2023, 4, 18.0, 2e9, 2.5e9);
    r.bps = 12.0;
    FundamentalSignal sig = compute_fundamental_signal({r}, 15.0, 500000000LL);
    EXPECT_EQ(sig.quarters_available, 1);
    EXPECT_NEAR(sig.roe_ttm, 18.0f, 0.1f);
    EXPECT_NEAR(sig.pb, 1.25f, 0.01f);
}

TEST(FundamentalSignal, YoYGrowthPositiveWhenGrowing) {
    // 5 quarters: quarter 5 net profit 50% higher than quarter 1
    std::vector<FinancialReport> hist;
    hist.push_back(make_report(2022, 4, 12, 1e9, 1.2e9));
    for (int q = 1; q <= 4; ++q)
        hist.push_back(make_report(2023, q, 14, 1.5e9, 1.7e9));
    FundamentalSignal sig = compute_fundamental_signal(hist, 10.0, 1000000000LL);
    EXPECT_GT(sig.profit_growth_yoy, 0.0f);
    EXPECT_GT(sig.revenue_growth_yoy, 0.0f);
}

TEST(FinancialReport, IsValidRequiresPositiveEquityAndRevenue) {
    FinancialReport r = make_report(2023, 1, 15, 1e9, 1.2e9);
    EXPECT_TRUE(r.is_valid());

    FinancialReport invalid;
    EXPECT_FALSE(invalid.is_valid());
}
