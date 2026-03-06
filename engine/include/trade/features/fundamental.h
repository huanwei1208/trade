#pragma once

#include "trade/features/feature_engine.h"
#include "trade/model/bar.h"
#include "trade/model/instrument.h"

#include <Eigen/Dense>
#include <map>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace trade {

// ============================================================================
// FundamentalCalculator  (Priority P9 -- Fundamental / PIT)
// ============================================================================
//
// Fundamental factors using Point-In-Time (PIT) methodology: values are
// only available from the announcement date, not the reporting period end.
// This avoids look-ahead bias that is common in fundamental factor research.
//
// Financial reports are keyed by (symbol, report_date, announce_date).
// At any evaluation date, we use the most recent report whose announce_date
// is <= the evaluation date.
//
// Features computed:
//
// --- Profitability (TTM = trailing twelve months) ---
//   roe_ttm                 net_income_TTM / avg_equity_TTM
//   roa_ttm                 net_income_TTM / avg_total_assets_TTM
//   roe_ttm_cs_rank         cross-sectional rank
//   roa_ttm_cs_rank         cross-sectional rank
//   roe_ttm_ts_z            ts_zscore(roe_ttm, 4Q lookback)
//
// --- Valuation ---
//   ep                      net_income_TTM / market_cap  (earnings/price)
//   bp                      book_value / market_cap       (book/price)
//   ep_cs_rank              cross-sectional rank
//   bp_cs_rank              cross-sectional rank
//
// --- Growth ---
//   revenue_yoy             (revenue_TTM / revenue_TTM_1yr_ago) - 1
//   profit_yoy              (net_income_TTM / net_income_TTM_1yr_ago) - 1
//   revenue_yoy_cs_rank     cross-sectional rank
//   profit_yoy_cs_rank      cross-sectional rank
//   revenue_yoy_ts_z        ts_zscore(revenue_yoy, 8Q lookback)
//   profit_yoy_ts_z         ts_zscore(profit_yoy, 8Q lookback)
//
// --- Cash flow quality ---
//   fcf_yield               free_cash_flow_TTM / market_cap
//   cfo_ni                  cash_from_operations_TTM / net_income_TTM
//   accruals                (net_income_TTM - cash_from_operations_TTM) /
//                           avg_total_assets_TTM
//   fcf_yield_cs_rank       cross-sectional rank
//   cfo_ni_cs_rank          cross-sectional rank
//   accruals_cs_rank        cross-sectional rank
//
// --- Earnings surprise ---
//   earnings_surprise       (actual_EPS - consensus_EPS) / |consensus_EPS|
//                           Only available on/after announcement date.
//   earnings_surprise_cs_rank   cross-sectional rank
//
// --- Data staleness ---
//   data_staleness          (eval_date - announce_date) in trading days
//                           Higher values = stale data, less reliable.
//   data_staleness_cs_rank  cross-sectional rank
//

// A single financial report record (PIT-aware)
struct FinancialReport {
    Symbol symbol;
    Date report_date;          // end of reporting period (e.g. 2024-06-30)
    Date announce_date;        // date the report was filed/released

    // Income statement (TTM or single period)
    double revenue = 0.0;
    double net_income = 0.0;
    double operating_income = 0.0;

    // Balance sheet (point-in-time snapshot)
    double total_assets = 0.0;
    double total_equity = 0.0;   // book value of equity
    double total_liabilities = 0.0;

    // Cash flow statement
    double cash_from_operations = 0.0;
    double capex = 0.0;
    double free_cash_flow = 0.0;  // CFO - capex

    // Per-share
    double eps = 0.0;
    std::optional<double> consensus_eps;  // analyst consensus (if available)

    // TTM aggregation helper: is this a full-year report?
    bool is_annual() const;

    // Quarter number: 1 (Q1), 2 (Q2/H1), 3 (Q3), 4 (Q4/annual)
    int quarter() const;
};

// TTM (trailing twelve months) computed from quarterly reports
struct TTMFinancials {
    double revenue = 0.0;
    double net_income = 0.0;
    double cash_from_operations = 0.0;
    double free_cash_flow = 0.0;
    double avg_total_assets = 0.0;
    double avg_equity = 0.0;
    double book_value = 0.0;       // latest equity
    double eps = 0.0;
    std::optional<double> consensus_eps;
    Date announce_date;            // latest report's announce date
};

class FundamentalCalculator : public FeatureCalculator {
public:
    // Financial reports keyed by symbol, sorted by announce_date within.
    using ReportMap = std::unordered_map<Symbol, std::vector<FinancialReport>>;

    // Market-cap data keyed by symbol (daily series aligned with dates).
    struct MktCapData {
        std::unordered_map<Symbol, Eigen::VectorXd> total_mktcap;  // yuan
    };

    FundamentalCalculator(ReportMap reports, MktCapData mktcap);

    std::string group_name() const override { return "fundamental"; }

    FeatureSet compute(
        const std::vector<BarSeries>& series,
        const std::unordered_map<Symbol, Instrument>& instruments) const override;

    // --- PIT helpers (static for unit-testing) ----------------------------

    // Get the most recent report available at |eval_date| using PIT logic:
    // announce_date <= eval_date, and pick the latest.
    static const FinancialReport* pit_lookup(
        const std::vector<FinancialReport>& reports, Date eval_date);

    // Compute TTM financials from a sequence of quarterly reports.
    // Uses the standard formula:
    //   TTM = Q4_annual   (if latest is Q4)
    //   TTM = latest_cumulative + prev_annual - prev_same_cumulative
    static std::optional<TTMFinancials> compute_ttm(
        const std::vector<FinancialReport>& reports, Date eval_date);

    // Compute year-over-year growth rate.
    // Returns NaN if the year-ago value is zero or unavailable.
    static double yoy_growth(double current_ttm, double prior_ttm);

    // Data staleness in trading days
    static int data_staleness(Date eval_date, Date announce_date);

    // Earnings surprise: (actual - consensus) / |consensus|
    static double earnings_surprise(double actual_eps,
                                    std::optional<double> consensus_eps);

    // Feature names for all fundamental features
    static std::vector<std::string> feature_names();

private:
    ReportMap reports_;
    MktCapData mktcap_;
};

} // namespace trade
