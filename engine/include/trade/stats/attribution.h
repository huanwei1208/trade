#pragma once

#include "trade/common/types.h"
#include "trade/model/bar.h"
#include "trade/model/instrument.h"
#include <Eigen/Dense>
#include <vector>
#include <string>
#include <unordered_map>

namespace trade {

// ---------------------------------------------------------------------------
// Brinson attribution: market / industry / stock-selection decomposition
// ---------------------------------------------------------------------------
struct BrinsonResult {
    Date start_date;
    Date end_date;

    double total_return = 0.0;          // portfolio return over the period
    double benchmark_return = 0.0;      // benchmark return over the period
    double active_return = 0.0;         // total - benchmark

    // Brinson-Fachler decomposition
    double allocation_effect = 0.0;     // sector/industry over/under-weight
    double selection_effect = 0.0;      // stock picking within sectors
    double interaction_effect = 0.0;    // cross term
    // allocation + selection + interaction = active_return

    // Per-industry breakdown (keyed by SWIndustry)
    struct IndustryDetail {
        SWIndustry industry = SWIndustry::kUnknown;
        double portfolio_weight = 0.0;
        double benchmark_weight = 0.0;
        double portfolio_return = 0.0;
        double benchmark_return = 0.0;
        double allocation = 0.0;
        double selection = 0.0;
        double interaction = 0.0;
    };
    std::vector<IndustryDetail> industry_details;
};

// ---------------------------------------------------------------------------
// Factor attribution: contribution of each factor to portfolio return
// ---------------------------------------------------------------------------
struct FactorContribution {
    std::string factor_name;
    double exposure = 0.0;             // portfolio factor exposure (z-score)
    double factor_return = 0.0;        // cross-sectional factor return
    double contribution = 0.0;         // exposure * factor_return
};

struct FactorAttributionResult {
    Date start_date;
    Date end_date;
    double total_return = 0.0;
    double factor_return = 0.0;        // sum of all factor contributions
    double specific_return = 0.0;      // residual (total - factor)
    std::vector<FactorContribution> factors;
};

// ---------------------------------------------------------------------------
// Anomaly detection results
// ---------------------------------------------------------------------------
enum class AnomalyType : uint8_t {
    kVolumeSpike = 0,      // volume > k * rolling mean (e.g., k = 3)
    kPriceGapUp = 1,       // open >> prev_close beyond normal range
    kPriceGapDown = 2,     // open << prev_close beyond normal range
    kVolatilitySpike = 3,  // intraday range > k * rolling avg range
    kTurnoverSpike = 4,    // turnover rate > k * rolling mean
};

struct Anomaly {
    Symbol symbol;
    Date date;
    AnomalyType type = AnomalyType::kVolumeSpike;
    double observed_value = 0.0;   // the actual metric value
    double threshold = 0.0;        // the threshold it exceeded
    double z_score = 0.0;          // standardised distance from normal
    std::string description;
};

// ---------------------------------------------------------------------------
// Event labels: classify trading days by known events
// ---------------------------------------------------------------------------
enum class EventLabel : uint8_t {
    kNone = 0,
    kLimitUpHit = 1,           // hit upper price limit during the day
    kLimitDownHit = 2,         // hit lower price limit during the day
    kEarningsPreWindow = 3,    // within N days before earnings announcement
    kEarningsPostWindow = 4,   // within N days after earnings announcement
    kPolicyDate = 5,           // known policy event date (e.g., rate cut)
    kIndexRebalance = 6,       // index constituent rebalance date
    kIPO = 7,                  // IPO first trading day
    kSuspensionReturn = 8,     // first day back from suspension
};

struct EventTag {
    Symbol symbol;
    Date date;
    EventLabel label = EventLabel::kNone;
    std::string detail;        // human-readable detail
};

// ---------------------------------------------------------------------------
// ReturnAttribution: comprehensive return decomposition and event analysis
// ---------------------------------------------------------------------------
class ReturnAttribution {
public:
    // ----- Brinson model ---------------------------------------------------

    /// Perform Brinson-Fachler attribution.
    /// @param portfolio_weights  Map Symbol -> portfolio weight.
    /// @param benchmark_weights  Map Symbol -> benchmark weight.
    /// @param stock_returns      Map Symbol -> total return over period.
    /// @param instruments        Map Symbol -> Instrument (for industry info).
    /// @param start              Period start date.
    /// @param end                Period end date.
    static BrinsonResult brinson_attribution(
        const std::unordered_map<Symbol, double>& portfolio_weights,
        const std::unordered_map<Symbol, double>& benchmark_weights,
        const std::unordered_map<Symbol, double>& stock_returns,
        const std::unordered_map<Symbol, Instrument>& instruments,
        Date start, Date end);

    // ----- Factor attribution ----------------------------------------------

    /// Attribute portfolio returns to factor exposures.
    /// @param portfolio_weights  Map Symbol -> weight.
    /// @param factor_exposures   N x K matrix (N stocks, K factors) of exposures.
    /// @param factor_returns     K-vector of factor returns for the period.
    /// @param symbols            Ordered symbol list matching rows of factor_exposures.
    /// @param factor_names       Ordered factor name list matching columns.
    /// @param total_return       Portfolio total return.
    /// @param start              Period start date.
    /// @param end                Period end date.
    static FactorAttributionResult factor_attribution(
        const std::unordered_map<Symbol, double>& portfolio_weights,
        const Eigen::MatrixXd& factor_exposures,
        const Eigen::VectorXd& factor_returns,
        const std::vector<Symbol>& symbols,
        const std::vector<std::string>& factor_names,
        double total_return,
        Date start, Date end);

    // ----- Anomaly detection -----------------------------------------------

    /// Detect volume spikes.
    /// @param series     Time series of bars for a single stock.
    /// @param lookback   Rolling window length for mean/std calculation.
    /// @param threshold  Number of standard deviations to flag (default 3.0).
    static std::vector<Anomaly> detect_volume_spikes(
        const BarSeries& series,
        int lookback = 20,
        double threshold = 3.0);

    /// Detect price gaps (open significantly different from prev close).
    /// @param series     Time series of bars.
    /// @param threshold  Gap magnitude as fraction (e.g., 0.03 = 3%).
    static std::vector<Anomaly> detect_price_gaps(
        const BarSeries& series,
        double threshold = 0.03);

    /// Detect turnover rate spikes.
    static std::vector<Anomaly> detect_turnover_spikes(
        const BarSeries& series,
        int lookback = 20,
        double threshold = 3.0);

    /// Detect volatility spikes (intraday range).
    static std::vector<Anomaly> detect_volatility_spikes(
        const BarSeries& series,
        int lookback = 20,
        double threshold = 3.0);

    /// Run all anomaly detectors and merge results (sorted by date).
    static std::vector<Anomaly> detect_all_anomalies(
        const BarSeries& series,
        int lookback = 20,
        double spike_threshold = 3.0,
        double gap_threshold = 0.03);

    // ----- Event labelling -------------------------------------------------

    /// Label limit-up / limit-down hits from Bar data.
    static std::vector<EventTag> label_limit_hits(
        const std::vector<Bar>& bars);

    /// Label earnings announcement windows.
    /// @param symbol           Stock symbol.
    /// @param earnings_dates   Sorted list of announcement dates.
    /// @param trading_dates    All trading dates in scope.
    /// @param pre_days         Days before announcement to flag (default 5).
    /// @param post_days        Days after announcement to flag (default 5).
    static std::vector<EventTag> label_earnings_windows(
        const Symbol& symbol,
        const std::vector<Date>& earnings_dates,
        const std::vector<Date>& trading_dates,
        int pre_days = 5,
        int post_days = 5);

    /// Label policy event windows.
    /// @param symbol         Stock symbol.
    /// @param policy_dates   Map from Date to policy description string.
    /// @param trading_dates  All trading dates in scope.
    static std::vector<EventTag> label_policy_dates(
        const Symbol& symbol,
        const std::unordered_map<Date, std::string>& policy_dates,
        const std::vector<Date>& trading_dates);

    /// Label index rebalance dates.
    static std::vector<EventTag> label_index_rebalance(
        const Symbol& symbol,
        const std::vector<Date>& rebalance_dates,
        const std::vector<Date>& trading_dates);

    /// Merge multiple event tag vectors, sorted by date.
    static std::vector<EventTag> merge_events(
        const std::vector<std::vector<EventTag>>& tag_lists);
};

} // namespace trade
