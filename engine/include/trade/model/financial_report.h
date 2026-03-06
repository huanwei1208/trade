#pragma once
#include "trade/common/types.h"
#include <string>
#include <vector>

namespace trade {

enum class ReportPeriod { Q1, Q2, Q3, Annual };

// One quarterly/annual financial statement snapshot (from EastMoney)
struct FinancialReport {
    Symbol symbol;
    Date report_date;     // 报告期末 (e.g. 2024-03-31)
    Date publish_date;    // 披露日期
    ReportPeriod period = ReportPeriod::Q1;

    // Income
    double revenue       = 0;  // 营业收入 (元)
    double net_profit    = 0;  // 归母净利润 (元)
    double op_profit     = 0;  // 营业利润 (元)

    // Cash flow
    double op_cash_flow  = 0;  // 经营活动现金流净额 (元)

    // Balance sheet
    double total_assets  = 0;  // 总资产 (元)
    double total_equity  = 0;  // 归母所有者权益 (元)

    // Per share (already computed by provider)
    double eps           = 0;  // 每股收益 (元)
    double bps           = 0;  // 每股净资产 (元)
    double roe           = 0;  // 净资产收益率 (%)

    bool is_valid() const {
        return total_equity > 0 && revenue > 0;
    }
};

// Derived fundamental snapshot used as ML features (T-1 snapshot)
// Computed from a sorted history of FinancialReport + daily close prices.
struct FundamentalSignal {
    // Profitability
    float roe_ttm           = 0;  // TTM ROE (%) = sum of 4 quarters
    float roe_momentum      = 0;  // roe_ttm - roe_ttm_4q_ago (positive = improving)
    float profit_growth_yoy = 0;  // YoY net profit growth (ratio)
    float revenue_growth_yoy= 0;  // YoY revenue growth (ratio)

    // Quality
    float cash_flow_quality = 0;  // op_cash_flow / net_profit  (>1 = high quality)

    // Valuation (needs current price + shares)
    float pe_percentile     = 0;  // PE rank in 3-year rolling history [0,1]
    float pe_ttm            = 0;  // TTM P/E ratio (market cap / TTM net profit)
    float pb                = 0;  // P/B = price / bps

    // Coverage
    int quarters_available  = 0;  // how many quarters of data
};

// Compute FundamentalSignal from a sorted list of FinancialReport (ascending date)
// plus current price and total_shares (for PE/PB).
// history must be sorted ascending by report_date.
FundamentalSignal compute_fundamental_signal(
    const std::vector<FinancialReport>& history,
    double current_price,
    int64_t total_shares);

} // namespace trade
