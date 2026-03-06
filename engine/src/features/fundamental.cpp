#include "trade/features/fundamental.h"
#include <algorithm>
#include <cmath>

namespace trade {

// ============================================================================
// FinancialReport helpers
// ============================================================================

bool FinancialReport::is_annual() const {
    int month = 0;
    // Extract month from report_date
    auto ymd = std::chrono::year_month_day{report_date};
    month = static_cast<int>(static_cast<unsigned>(ymd.month()));
    return month == 12;
}

int FinancialReport::quarter() const {
    auto ymd = std::chrono::year_month_day{report_date};
    int month = static_cast<int>(static_cast<unsigned>(ymd.month()));
    if (month <= 3) return 1;
    if (month <= 6) return 2;
    if (month <= 9) return 3;
    return 4;
}

// ============================================================================
// FundamentalCalculator
// ============================================================================

FundamentalCalculator::FundamentalCalculator(ReportMap reports, MktCapData mktcap)
    : reports_(std::move(reports)), mktcap_(std::move(mktcap)) {}

// ============================================================================
// PIT lookup: find the most recent report whose announce_date <= eval_date
// ============================================================================

const FinancialReport* FundamentalCalculator::pit_lookup(
    const std::vector<FinancialReport>& reports, Date eval_date) {
    const FinancialReport* best = nullptr;

    for (const auto& r : reports) {
        if (r.announce_date <= eval_date) {
            if (!best || r.announce_date > best->announce_date) {
                best = &r;
            } else if (r.announce_date == best->announce_date &&
                       r.report_date > best->report_date) {
                // Same announce date, prefer more recent reporting period
                best = &r;
            }
        }
    }
    return best;
}

// ============================================================================
// TTM computation from quarterly reports
// ============================================================================

std::optional<TTMFinancials> FundamentalCalculator::compute_ttm(
    const std::vector<FinancialReport>& reports, Date eval_date) {
    // Find the latest available report (PIT)
    const FinancialReport* latest = pit_lookup(reports, eval_date);
    if (!latest) return std::nullopt;

    TTMFinancials ttm;
    ttm.announce_date = latest->announce_date;
    ttm.book_value = latest->total_equity;
    ttm.eps = latest->eps;
    ttm.consensus_eps = latest->consensus_eps;

    int q = latest->quarter();

    if (q == 4) {
        // Annual report: TTM = annual figures directly
        ttm.revenue = latest->revenue;
        ttm.net_income = latest->net_income;
        ttm.cash_from_operations = latest->cash_from_operations;
        ttm.free_cash_flow = latest->free_cash_flow;
        ttm.avg_total_assets = latest->total_assets;
        ttm.avg_equity = latest->total_equity;
        return ttm;
    }

    // For interim reports: TTM = latest_cumulative + prev_annual - prev_same_cumulative
    // Find previous annual report (Q4 of the previous year)
    auto ymd_latest = std::chrono::year_month_day{latest->report_date};
    int report_year = static_cast<int>(ymd_latest.year());

    const FinancialReport* prev_annual = nullptr;
    const FinancialReport* prev_same_cumulative = nullptr;

    for (const auto& r : reports) {
        if (r.announce_date > eval_date) continue;  // PIT constraint

        auto ymd_r = std::chrono::year_month_day{r.report_date};
        int r_year = static_cast<int>(ymd_r.year());

        // Previous year annual
        if (r_year == report_year - 1 && r.quarter() == 4) {
            if (!prev_annual || r.announce_date > prev_annual->announce_date) {
                prev_annual = &r;
            }
        }

        // Previous year same quarter cumulative
        if (r_year == report_year - 1 && r.quarter() == q) {
            if (!prev_same_cumulative || r.announce_date > prev_same_cumulative->announce_date) {
                prev_same_cumulative = &r;
            }
        }
    }

    if (!prev_annual || !prev_same_cumulative) {
        // Fallback: just use annualized from latest cumulative
        double annualize_factor = 4.0 / q;
        ttm.revenue = latest->revenue * annualize_factor;
        ttm.net_income = latest->net_income * annualize_factor;
        ttm.cash_from_operations = latest->cash_from_operations * annualize_factor;
        ttm.free_cash_flow = latest->free_cash_flow * annualize_factor;
        ttm.avg_total_assets = latest->total_assets;
        ttm.avg_equity = latest->total_equity;
        return ttm;
    }

    // TTM = latest_cumulative + prev_annual - prev_same_cumulative
    ttm.revenue = latest->revenue + prev_annual->revenue - prev_same_cumulative->revenue;
    ttm.net_income = latest->net_income + prev_annual->net_income - prev_same_cumulative->net_income;
    ttm.cash_from_operations = latest->cash_from_operations +
                               prev_annual->cash_from_operations -
                               prev_same_cumulative->cash_from_operations;
    ttm.free_cash_flow = latest->free_cash_flow +
                         prev_annual->free_cash_flow -
                         prev_same_cumulative->free_cash_flow;

    // Average total assets: (latest + prev_annual) / 2
    ttm.avg_total_assets = (latest->total_assets + prev_annual->total_assets) / 2.0;
    // Average equity: (latest + prev_annual) / 2
    ttm.avg_equity = (latest->total_equity + prev_annual->total_equity) / 2.0;

    return ttm;
}

// ============================================================================
// Helper functions
// ============================================================================

double FundamentalCalculator::yoy_growth(double current_ttm, double prior_ttm) {
    if (std::abs(prior_ttm) < 1e-8) return std::numeric_limits<double>::quiet_NaN();
    return current_ttm / prior_ttm - 1.0;
}

int FundamentalCalculator::data_staleness(Date eval_date, Date announce_date) {
    // Approximate trading days between announce_date and eval_date
    // Rough heuristic: calendar days * 5/7 (excluding weekends)
    auto diff = (eval_date - announce_date).count();
    if (diff < 0) return 0;
    return static_cast<int>(diff * 5.0 / 7.0);
}

double FundamentalCalculator::earnings_surprise(
    double actual_eps, std::optional<double> consensus_eps) {
    if (!consensus_eps || std::abs(*consensus_eps) < 1e-10) {
        return std::numeric_limits<double>::quiet_NaN();
    }
    return (actual_eps - *consensus_eps) / std::abs(*consensus_eps);
}

std::vector<std::string> FundamentalCalculator::feature_names() {
    return {
        "roe_ttm",                  // 0
        "roa_ttm",                  // 1
        "roe_ttm_cs_rank",          // 2
        "roa_ttm_cs_rank",          // 3
        "roe_ttm_ts_z",             // 4
        "ep",                       // 5
        "bp",                       // 6
        "ep_cs_rank",               // 7
        "bp_cs_rank",               // 8
        "revenue_yoy",              // 9
        "profit_yoy",               // 10
        "revenue_yoy_cs_rank",      // 11
        "profit_yoy_cs_rank",       // 12
        "revenue_yoy_ts_z",         // 13
        "profit_yoy_ts_z",          // 14
        "fcf_yield",                // 15
        "cfo_ni",                   // 16
        "accruals",                 // 17
        "fcf_yield_cs_rank",        // 18
        "cfo_ni_cs_rank",           // 19
        "accruals_cs_rank",         // 20
        "earnings_surprise",        // 21
        "earnings_surprise_cs_rank",// 22
        "data_staleness",           // 23
        "data_staleness_cs_rank",   // 24
    };
}

// ============================================================================
// Main compute
// ============================================================================

FeatureSet FundamentalCalculator::compute(
    const std::vector<BarSeries>& series,
    const std::unordered_map<Symbol, Instrument>& /*instruments*/) const {
    if (series.empty()) return {};

    int n_stocks = static_cast<int>(series.size());
    auto names = feature_names();
    constexpr int n_features = 25;

    Eigen::MatrixXd mat(n_stocks, n_features);
    mat.setConstant(std::numeric_limits<double>::quiet_NaN());

    std::vector<Symbol> symbols;
    std::vector<Date> dates;

    for (int s = 0; s < n_stocks; ++s) {
        const auto& bs = series[s];
        symbols.push_back(bs.symbol);
        Date eval_date = bs.empty() ? Date{} : bs.bars.back().date;
        dates.push_back(eval_date);

        // Look up financial reports for this symbol
        auto report_it = reports_.find(bs.symbol);
        if (report_it == reports_.end() || report_it->second.empty()) continue;

        const auto& stock_reports = report_it->second;

        // Compute TTM financials
        auto ttm_opt = compute_ttm(stock_reports, eval_date);
        if (!ttm_opt) continue;

        const auto& ttm = *ttm_opt;

        // Get market cap for this stock at eval_date
        double mktcap = std::numeric_limits<double>::quiet_NaN();
        auto mc_it = mktcap_.total_mktcap.find(bs.symbol);
        if (mc_it != mktcap_.total_mktcap.end() && mc_it->second.size() > 0) {
            mktcap = mc_it->second(mc_it->second.size() - 1);
        }

        // Profitability
        if (std::abs(ttm.avg_equity) > 1e-8) {
            mat(s, 0) = ttm.net_income / ttm.avg_equity;   // ROE TTM
        }
        if (std::abs(ttm.avg_total_assets) > 1e-8) {
            mat(s, 1) = ttm.net_income / ttm.avg_total_assets;  // ROA TTM
        }

        // Valuation
        if (!std::isnan(mktcap) && mktcap > 1e-8) {
            mat(s, 5) = ttm.net_income / mktcap;     // EP
            mat(s, 6) = ttm.book_value / mktcap;     // BP
            mat(s, 15) = ttm.free_cash_flow / mktcap; // FCF yield
        }

        // Growth: need TTM from one year ago
        // Find the report from ~1 year ago
        Date one_year_ago = eval_date - std::chrono::days(365);
        auto ttm_prev = compute_ttm(stock_reports, one_year_ago);
        if (ttm_prev) {
            mat(s, 9) = yoy_growth(ttm.revenue, ttm_prev->revenue);
            mat(s, 10) = yoy_growth(ttm.net_income, ttm_prev->net_income);
        }

        // Cash flow quality
        if (std::abs(ttm.net_income) > 1e-8) {
            mat(s, 16) = ttm.cash_from_operations / ttm.net_income;  // CFO/NI
        }
        if (std::abs(ttm.avg_total_assets) > 1e-8) {
            mat(s, 17) = (ttm.net_income - ttm.cash_from_operations) /
                          ttm.avg_total_assets;  // accruals
        }

        // Earnings surprise
        mat(s, 21) = earnings_surprise(ttm.eps, ttm.consensus_eps);

        // Data staleness
        mat(s, 23) = static_cast<double>(data_staleness(eval_date, ttm.announce_date));

        // ts_z for ROE: compute from historical quarterly ROE values
        // Collect historical ROE values (up to 8 quarters back)
        std::vector<double> roe_history;
        for (int q_back = 0; q_back < 8; ++q_back) {
            Date look_date = eval_date - std::chrono::days(90 * q_back);
            auto hist_ttm = compute_ttm(stock_reports, look_date);
            if (hist_ttm && std::abs(hist_ttm->avg_equity) > 1e-8) {
                roe_history.push_back(hist_ttm->net_income / hist_ttm->avg_equity);
            } else {
                roe_history.push_back(std::numeric_limits<double>::quiet_NaN());
            }
        }
        // ts_z of ROE
        if (roe_history.size() >= 4) {
            Eigen::VectorXd roe_vec(static_cast<int>(roe_history.size()));
            // Reverse so oldest is first
            for (int i = 0; i < static_cast<int>(roe_history.size()); ++i) {
                roe_vec(i) = roe_history[roe_history.size() - 1 - i];
            }
            auto roe_tz = ts_zscore(roe_vec, static_cast<int>(roe_vec.size()));
            if (roe_tz.size() > 0) {
                mat(s, 4) = roe_tz(roe_tz.size() - 1);
            }
        }

        // ts_z for revenue_yoy and profit_yoy (similar approach)
        std::vector<double> rev_yoy_hist, profit_yoy_hist;
        for (int q_back = 0; q_back < 8; ++q_back) {
            Date look_date = eval_date - std::chrono::days(90 * q_back);
            Date look_date_prev = look_date - std::chrono::days(365);
            auto hist_ttm = compute_ttm(stock_reports, look_date);
            auto hist_ttm_prev = compute_ttm(stock_reports, look_date_prev);
            if (hist_ttm && hist_ttm_prev) {
                rev_yoy_hist.push_back(yoy_growth(hist_ttm->revenue, hist_ttm_prev->revenue));
                profit_yoy_hist.push_back(yoy_growth(hist_ttm->net_income, hist_ttm_prev->net_income));
            } else {
                rev_yoy_hist.push_back(std::numeric_limits<double>::quiet_NaN());
                profit_yoy_hist.push_back(std::numeric_limits<double>::quiet_NaN());
            }
        }

        auto compute_ts_z_from_hist = [](const std::vector<double>& hist) -> double {
            if (hist.size() < 4) return std::numeric_limits<double>::quiet_NaN();
            Eigen::VectorXd vec(static_cast<int>(hist.size()));
            for (int i = 0; i < static_cast<int>(hist.size()); ++i) {
                vec(i) = hist[hist.size() - 1 - i];  // reverse: oldest first
            }
            auto tz = ts_zscore(vec, static_cast<int>(vec.size()));
            return (tz.size() > 0) ? tz(tz.size() - 1) : std::numeric_limits<double>::quiet_NaN();
        };

        mat(s, 13) = compute_ts_z_from_hist(rev_yoy_hist);
        mat(s, 14) = compute_ts_z_from_hist(profit_yoy_hist);
    }

    // Cross-sectional ranks
    mat.col(2)  = cs_rank(mat.col(0));    // roe_ttm_cs_rank
    mat.col(3)  = cs_rank(mat.col(1));    // roa_ttm_cs_rank
    mat.col(7)  = cs_rank(mat.col(5));    // ep_cs_rank
    mat.col(8)  = cs_rank(mat.col(6));    // bp_cs_rank
    mat.col(11) = cs_rank(mat.col(9));    // revenue_yoy_cs_rank
    mat.col(12) = cs_rank(mat.col(10));   // profit_yoy_cs_rank
    mat.col(18) = cs_rank(mat.col(15));   // fcf_yield_cs_rank
    mat.col(19) = cs_rank(mat.col(16));   // cfo_ni_cs_rank
    mat.col(20) = cs_rank(mat.col(17));   // accruals_cs_rank
    mat.col(22) = cs_rank(mat.col(21));   // earnings_surprise_cs_rank
    mat.col(24) = cs_rank(mat.col(23));   // data_staleness_cs_rank

    FeatureSet fs;
    fs.names = names;
    fs.symbols = std::move(symbols);
    fs.dates = std::move(dates);
    fs.matrix = std::move(mat);
    return fs;
}

} // namespace trade
