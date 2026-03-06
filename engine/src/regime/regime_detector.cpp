#include "trade/regime/regime_detector.h"
#include <algorithm>
#include <cmath>
#include <numeric>

namespace trade {

double RegimeDetector::sma(const std::vector<double>& prices, int period) {
    if (prices.empty() || period <= 0) return 0.0;
    int n = std::min(period, static_cast<int>(prices.size()));
    double sum = 0.0;
    for (int i = static_cast<int>(prices.size()) - n;
         i < static_cast<int>(prices.size()); ++i) {
        sum += prices[i];
    }
    return sum / n;
}

double RegimeDetector::realized_vol(const std::vector<double>& prices, int window) {
    int n = static_cast<int>(prices.size());
    if (n < window + 1) return 0.0;

    // Compute daily returns for last `window` days
    double sum = 0, sum2 = 0;
    int count = 0;
    for (int i = n - window; i < n; ++i) {
        if (prices[i - 1] > 0) {
            double ret = prices[i] / prices[i - 1] - 1.0;
            sum += ret;
            sum2 += ret * ret;
            ++count;
        }
    }
    if (count < 2) return 0.0;
    double mean = sum / count;
    double var = (sum2 / count) - mean * mean;
    if (var <= 0) return 0.0;

    // Annualize: sqrt(252) * daily_std
    return std::sqrt(var * 252.0);
}

double RegimeDetector::trend_slope(const std::vector<double>& prices, int window) {
    int n = static_cast<int>(prices.size());
    if (n < window) return 0.0;

    // Simple linear regression y = a + b*x over last `window` prices
    // x = 0, 1, ..., window-1
    int start = n - window;
    double mean_price = 0;
    for (int i = start; i < n; ++i) mean_price += prices[i];
    mean_price /= window;

    double mean_x = (window - 1.0) / 2.0;
    double sum_xy = 0, sum_xx = 0;
    for (int i = 0; i < window; ++i) {
        double dx = i - mean_x;
        double dy = prices[start + i] - mean_price;
        sum_xy += dx * dy;
        sum_xx += dx * dx;
    }

    if (sum_xx < 1e-15 || mean_price < 1e-15) return 0.0;
    double slope = sum_xy / sum_xx;
    // Normalize by mean price so it's scale-independent
    return slope / mean_price;
}

double RegimeDetector::quantile_rank(double value,
                                      const std::vector<double>& distribution) {
    if (distribution.empty()) return 0.5;
    int below = 0;
    for (double v : distribution) {
        if (v < value) ++below;
    }
    return static_cast<double>(below) / static_cast<double>(distribution.size());
}

RegimeDetector::VolRegime RegimeDetector::detect_vol_regime(
    const std::vector<double>& vol_history) const {
    if (vol_history.empty()) return VolRegime::kNormal;

    // Use the last value as current vol
    double current = vol_history.back();

    // Compute tercile thresholds
    std::vector<double> sorted = vol_history;
    std::sort(sorted.begin(), sorted.end());
    int n = static_cast<int>(sorted.size());

    double low_thresh = sorted[n / 3];
    double high_thresh = sorted[2 * n / 3];

    if (current <= low_thresh) return VolRegime::kLow;
    if (current >= high_thresh) return VolRegime::kHigh;
    return VolRegime::kNormal;
}

RegimeDetector::RegimeResult RegimeDetector::detect(
    const std::vector<double>& index_prices,
    const MarketBreadth& market_breadth) const {

    RegimeResult r;
    int n = static_cast<int>(index_prices.size());

    if (n == 0) return r;

    r.index_price = index_prices.back();
    r.up_ratio = market_breadth.up_ratio();

    // 120-day moving average
    r.dma_120 = sma(index_prices, config_.dma_period);
    r.index_above_dma_pct = (r.dma_120 > 0)
        ? (r.index_price / r.dma_120 - 1.0) : 0.0;

    // Realized vol (annualized)
    r.annualised_vol = realized_vol(index_prices, config_.realized_vol_window);

    // Single-day return
    if (n >= 2 && index_prices[n - 2] > 0) {
        r.single_day_return = index_prices[n - 1] / index_prices[n - 2] - 1.0;
    }

    // Trend slope
    r.trend_slope = trend_slope(index_prices, config_.trend_window);
    r.trend_down = r.trend_slope < 0;

    // Vol regime
    if (n >= config_.realized_vol_window + 1) {
        // Build vol history
        int hist_len = std::min(config_.vol_history_days, n - config_.realized_vol_window);
        std::vector<double> vol_hist;
        vol_hist.reserve(hist_len);
        for (int i = n - hist_len; i <= n - 1; ++i) {
            int start = std::max(0, i - config_.realized_vol_window);
            // Subset of prices for this window
            std::vector<double> sub(index_prices.begin() + start,
                                     index_prices.begin() + i + 1);
            if (static_cast<int>(sub.size()) > config_.realized_vol_window) {
                vol_hist.push_back(realized_vol(sub, config_.realized_vol_window));
            }
        }

        if (!vol_hist.empty()) {
            r.vol_regime = detect_vol_regime(vol_hist);
            r.vol_quantile = quantile_rank(r.annualised_vol, vol_hist);

            std::sort(vol_hist.begin(), vol_hist.end());
            int vn = static_cast<int>(vol_hist.size());
            r.vol_tercile_low = vol_hist[vn / 3];
            r.vol_tercile_high = vol_hist[2 * vn / 3];
        }
    }

    // Check shock triggers
    r.shock_vol_trigger = (r.annualised_vol > config_.shock_vol_threshold);
    r.shock_day_trigger = (std::abs(r.single_day_return) > config_.shock_day_return_threshold);

    // Market regime classification
    if (r.shock_vol_trigger || r.shock_day_trigger) {
        r.market_regime = Regime::kShock;
    } else if (r.index_price > r.dma_120 &&
               r.up_ratio >= config_.bull_up_ratio_min &&
               r.annualised_vol < config_.bull_vol_max) {
        r.market_regime = Regime::kBull;
    } else if (r.index_price < r.dma_120 &&
               r.up_ratio <= config_.bear_up_ratio_max &&
               r.trend_down) {
        r.market_regime = Regime::kBear;
    } else {
        // Default: maintain bear/bull based on DMA position
        r.market_regime = (r.index_price >= r.dma_120) ? Regime::kBull : Regime::kBear;
    }

    return r;
}

RegimeDetector::RegimeResult RegimeDetector::update(
    const std::vector<double>& index_prices,
    const MarketBreadth& market_breadth) {

    auto result = detect(index_prices, market_breadth);

    // Shock always takes effect immediately (no persistence delay)
    if (result.market_regime == Regime::kShock) {
        confirmed_regime_ = Regime::kShock;
        pending_regime_ = Regime::kShock;
        pending_count_ = 0;
        regime_duration_ = 1;
        result.market_regime = confirmed_regime_;
        return result;
    }

    // Persistence filter: require N consecutive days before switching
    if (result.market_regime == pending_regime_) {
        ++pending_count_;
    } else {
        pending_regime_ = result.market_regime;
        pending_count_ = 1;
    }

    if (pending_count_ >= config_.min_persistence_days &&
        pending_regime_ != confirmed_regime_) {
        confirmed_regime_ = pending_regime_;
        regime_duration_ = 0;
    }

    ++regime_duration_;
    confirmed_vol_regime_ = result.vol_regime;

    // Override result with confirmed regime
    result.market_regime = confirmed_regime_;
    return result;
}

} // namespace trade
