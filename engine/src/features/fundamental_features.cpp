#include "trade/model/financial_report.h"

#include <algorithm>
#include <cmath>
#include <numeric>

namespace trade {

FundamentalSignal compute_fundamental_signal(
    const std::vector<FinancialReport>& history,
    double current_price,
    int64_t total_shares)
{
    FundamentalSignal sig{};

    if (history.empty()) return sig;

    // Use at most 12 quarters
    int n = static_cast<int>(history.size());
    int q_avail = std::min(n, 12);
    sig.quarters_available = q_avail;

    // Most recent quarter is at index n-1 (history sorted ascending)
    // Last 4 quarters: indices [n-4, n-1] (or fewer if not available)
    int last4_start = std::max(0, n - 4);
    int last4_count = n - last4_start;  // number of quarters in last-4 window

    // ── TTM ROE: average of last 4 quarters' roe fields ──────────────────
    {
        double roe_sum = 0.0;
        for (int i = last4_start; i < n; ++i) {
            roe_sum += history[i].roe;
        }
        sig.roe_ttm = static_cast<float>(roe_sum / last4_count);
    }

    // ── ROE momentum: roe_ttm minus roe 4 quarters ago ───────────────────
    // "4 quarters ago" means compute roe_ttm using the 4Q window that ended
    // 4 quarters before the current last quarter.
    {
        // Window for "4 quarters ago": [n-8, n-5), i.e. indices [n-8..n-5]
        int prev4_end   = n - 4;    // exclusive end (= last4_start)
        int prev4_start = std::max(0, n - 8);
        if (prev4_end > prev4_start) {
            double prev_roe_sum = 0.0;
            int prev4_count = prev4_end - prev4_start;
            for (int i = prev4_start; i < prev4_end; ++i) {
                prev_roe_sum += history[i].roe;
            }
            float prev_roe_ttm = static_cast<float>(prev_roe_sum / prev4_count);
            sig.roe_momentum = sig.roe_ttm - prev_roe_ttm;
        }
        // If fewer than 5 quarters available, roe_momentum stays 0
    }

    // ── YoY growth: compare last quarter to same quarter prior year ───────
    {
        // "Same quarter prior year" = index n-5 (1 year = 4 quarters back)
        if (n >= 5) {
            const FinancialReport& latest     = history[n - 1];
            const FinancialReport& year_ago   = history[n - 5];
            double prior_profit  = year_ago.net_profit;
            double prior_revenue = year_ago.revenue;

            if (std::abs(prior_profit) > 1.0) {
                sig.profit_growth_yoy = static_cast<float>(
                    (latest.net_profit - prior_profit) / std::abs(prior_profit));
            }
            if (prior_revenue > 1.0) {
                sig.revenue_growth_yoy = static_cast<float>(
                    (latest.revenue - prior_revenue) / prior_revenue);
            }
        }
    }

    // ── Cash flow quality: sum(op_cf last 4Q) / sum(net_profit last 4Q) ──
    {
        double cf_sum = 0.0;
        double np_sum = 0.0;
        for (int i = last4_start; i < n; ++i) {
            cf_sum += history[i].op_cash_flow;
            np_sum += history[i].net_profit;
        }
        if (std::abs(np_sum) > 1.0) {
            double cfq = cf_sum / np_sum;
            // Clamp to [-3, 5]
            cfq = std::clamp(cfq, -3.0, 5.0);
            sig.cash_flow_quality = static_cast<float>(cfq);
        }
        // else: leave at 0
    }

    // ── PE TTM: (current_price * total_shares) / sum(net_profit last 4Q) ─
    double ttm_net_profit = 0.0;
    for (int i = last4_start; i < n; ++i) {
        ttm_net_profit += history[i].net_profit;
    }

    if (std::abs(ttm_net_profit) > 1.0 && total_shares > 0 && current_price > 0.0) {
        double market_cap = current_price * static_cast<double>(total_shares);
        double pe = market_cap / ttm_net_profit;
        pe = std::clamp(pe, 1.0, 300.0);
        sig.pe_ttm = static_cast<float>(pe);
    }
    // else leave pe_ttm at 0

    // ── PB: current_price / bps of most recent report ────────────────────
    {
        double bps = history[n - 1].bps;
        if (bps > 1e-6 && current_price > 0.0) {
            double pb = current_price / bps;
            pb = std::clamp(pb, 0.1, 50.0);
            sig.pb = static_cast<float>(pb);
        }
    }

    // ── PE percentile: rank of pe_ttm among last 12 quarterly pe_ttm ─────
    // Compute a pe_ttm for each of the last 12 quarters (or fewer if not available)
    if (sig.pe_ttm > 0.0f && total_shares > 0 && current_price > 0.0) {
        // For each quarter i in [n-q_avail, n-1], compute pe at that quarter
        // using the 4-quarter trailing net profit ending at quarter i.
        std::vector<float> pe_history;
        pe_history.reserve(q_avail);

        int hist_start = n - q_avail;  // = max(0, n-12)
        for (int i = hist_start; i < n; ++i) {
            // TTM profit ending at quarter i: sum quarters [i-3..i]
            double np = 0.0;
            int cnt = 0;
            for (int j = std::max(0, i - 3); j <= i; ++j) {
                np += history[j].net_profit;
                ++cnt;
            }
            if (std::abs(np) > 1.0 && cnt > 0) {
                double mkt = current_price * static_cast<double>(total_shares);
                double pe_i = mkt / np;
                if (pe_i > 0.0) {
                    pe_i = std::clamp(pe_i, 1.0, 300.0);
                    pe_history.push_back(static_cast<float>(pe_i));
                }
            }
        }

        if (pe_history.size() > 1) {
            float current_pe = sig.pe_ttm;
            int rank = 0;
            for (float pe_hist : pe_history) {
                if (pe_hist < current_pe) ++rank;
            }
            sig.pe_percentile = static_cast<float>(rank) /
                                 static_cast<float>(pe_history.size());
        }
    }

    return sig;
}

} // namespace trade
