#include "trade/features/technical_signals.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <fmt/format.h>
#include <numeric>

namespace trade {

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

namespace {

// Extract ISO date string from a Bar
static std::string bar_date_str(const Bar& bar) {
    auto dp = std::chrono::floor<std::chrono::days>(bar.date);
    auto ymd = std::chrono::year_month_day{dp};
    return fmt::format("{:04d}-{:02d}-{:02d}",
        static_cast<int>(ymd.year()),
        static_cast<unsigned>(ymd.month()),
        static_cast<unsigned>(ymd.day()));
}

// EMA helper: returns EMA vector of length n
// alpha = 2 / (period + 1)
static std::vector<double> ema_series(const std::vector<double>& src, int period) {
    std::vector<double> out(src.size(), 0.0);
    if (src.empty()) return out;
    double alpha = 2.0 / (period + 1);
    out[0] = src[0];
    for (size_t i = 1; i < src.size(); ++i) {
        out[i] = alpha * src[i] + (1.0 - alpha) * out[i - 1];
    }
    return out;
}

// Wilder's smoothing EMA (alpha = 1/period)
static std::vector<double> wilder_ema(const std::vector<double>& src, int period) {
    std::vector<double> out(src.size(), 0.0);
    if (src.empty()) return out;
    double alpha = 1.0 / period;
    out[0] = src[0];
    for (size_t i = 1; i < src.size(); ++i) {
        out[i] = alpha * src[i] + (1.0 - alpha) * out[i - 1];
    }
    return out;
}

// Lowest of a window ending at index i
static double lowest_low(const std::vector<double>& lows, int i, int period) {
    int start = std::max(0, i - period + 1);
    double lo = lows[start];
    for (int j = start + 1; j <= i; ++j) {
        lo = std::min(lo, lows[j]);
    }
    return lo;
}

// Highest of a window ending at index i
static double highest_high(const std::vector<double>& highs, int i, int period) {
    int start = std::max(0, i - period + 1);
    double hi = highs[start];
    for (int j = start + 1; j <= i; ++j) {
        hi = std::max(hi, highs[j]);
    }
    return hi;
}

// Rolling mean of a window ending at index i
static double rolling_avg(const std::vector<double>& v, int i, int window) {
    int start = std::max(0, i - window + 1);
    double sum = 0.0;
    int cnt = i - start + 1;
    for (int j = start; j <= i; ++j) sum += v[j];
    return sum / cnt;
}

// Rolling std (sample) of a window ending at index i
static double rolling_std_val(const std::vector<double>& v, int i, int window) {
    int start = std::max(0, i - window + 1);
    int cnt = i - start + 1;
    if (cnt < 2) return 0.0;
    double mean = rolling_avg(v, i, window);
    double var = 0.0;
    for (int j = start; j <= i; ++j) {
        double d = v[j] - mean;
        var += d * d;
    }
    return std::sqrt(var / (cnt - 1));
}

// Linear slope of a window ending at index i (simple least squares)
static double linear_slope(const std::vector<double>& v, int i, int window) {
    int start = std::max(0, i - window + 1);
    int cnt = i - start + 1;
    if (cnt < 2) return 0.0;
    double sx = 0.0, sy = 0.0, sxy = 0.0, sxx = 0.0;
    for (int j = start; j <= i; ++j) {
        double x = static_cast<double>(j - start);
        sx += x;
        sy += v[j];
        sxy += x * v[j];
        sxx += x * x;
    }
    double denom = cnt * sxx - sx * sx;
    if (std::abs(denom) < 1e-12) return 0.0;
    return (cnt * sxy - sx * sy) / denom;
}

// Classify divergence: +1=positive (both new high), -1=negative (price new high but indicator not)
//   0 = no new high or both not making new high
static int divergence_signal(
    const std::vector<double>& prices,
    const std::vector<double>& indicator,
    int i, int lookback = 20)
{
    int start = std::max(0, i - lookback + 1);
    if (i <= start) return 0;
    double max_price_old = *std::max_element(prices.begin() + start,
                                              prices.begin() + i);
    double max_ind_old   = *std::max_element(indicator.begin() + start,
                                              indicator.begin() + i);
    double cur_price = prices[i];
    double cur_ind   = indicator[i];

    bool price_new_high = cur_price > max_price_old;
    bool ind_new_high   = cur_ind   > max_ind_old;

    if (!price_new_high) return 0;
    return ind_new_high ? 1 : -1;  // -1=negative divergence (bearish warning)
}

} // anonymous namespace

// ---------------------------------------------------------------------------
// Main computation
// ---------------------------------------------------------------------------

TechnicalSignal compute_signals(const std::vector<Bar>& bars) {
    TechnicalSignal sig{};
    if (bars.empty()) return sig;

    int n = static_cast<int>(bars.size());

    // Extract price series
    std::vector<double> closes(n), highs(n), lows(n), volumes(n), turnover_rates(n);
    for (int i = 0; i < n; ++i) {
        closes[i]        = bars[i].close;
        highs[i]         = bars[i].high;
        lows[i]          = bars[i].low;
        volumes[i]       = static_cast<double>(bars[i].volume);
        turnover_rates[i]= bars[i].turnover_rate;
    }

    int last = n - 1;

    // ── KDJ (period=9) ─────────────────────────────────────────────────────
    // RSV = (close - lowest_low_9) / (highest_high_9 - lowest_low_9) * 100
    // K = 2/3 * prev_K + 1/3 * RSV   (initial K=50)
    // D = 2/3 * prev_D + 1/3 * K     (initial D=50)
    // J = 3K - 2D
    {
        constexpr int KDJ_PERIOD = 9;
        std::vector<double> K(n, 50.0), D(n, 50.0);
        for (int i = 0; i < n; ++i) {
            double ll = lowest_low(lows, i, KDJ_PERIOD);
            double hh = highest_high(highs, i, KDJ_PERIOD);
            double range = hh - ll;
            double rsv = (range < 1e-10) ? 50.0 : (closes[i] - ll) / range * 100.0;
            if (i == 0) {
                K[i] = 50.0 + (1.0 / 3.0) * (rsv - 50.0);
                D[i] = 50.0 + (1.0 / 3.0) * (K[i] - 50.0);
            } else {
                K[i] = (2.0 / 3.0) * K[i - 1] + (1.0 / 3.0) * rsv;
                D[i] = (2.0 / 3.0) * D[i - 1] + (1.0 / 3.0) * K[i];
            }
        }

        double kval = K[last];
        sig.kdj_zone = (kval < 20.0) ? 0 : (kval > 80.0) ? 2 : 1;

        // Golden/death cross: K crosses D
        if (last >= 1) {
            bool was_below = K[last - 1] < D[last - 1];
            bool now_above = K[last]     >= D[last];
            bool was_above = K[last - 1] >= D[last - 1];
            bool now_below = K[last]     <  D[last];
            if (was_below && now_above)       sig.kdj_cross = +1;
            else if (was_above && now_below)  sig.kdj_cross = -1;
        }

        sig.kdj_divergence = static_cast<float>(divergence_signal(closes, K, last));
    }

    // ── MACD (12, 26, 9) ──────────────────────────────────────────────────
    {
        auto ema12 = ema_series(closes, 12);
        auto ema26 = ema_series(closes, 26);
        std::vector<double> dif(n), signal_line(n), hist(n);
        for (int i = 0; i < n; ++i) dif[i] = ema12[i] - ema26[i];
        signal_line = ema_series(dif, 9);
        for (int i = 0; i < n; ++i) hist[i] = dif[i] - signal_line[i];

        if (last >= 1) {
            bool was_below = dif[last - 1] < signal_line[last - 1];
            bool now_above = dif[last]     >= signal_line[last];
            bool was_above = dif[last - 1] >= signal_line[last - 1];
            bool now_below = dif[last]     <  signal_line[last];
            if (was_below && now_above)       sig.macd_cross = +1;
            else if (was_above && now_below)  sig.macd_cross = -1;
        }

        // Histogram slope over last 5 bars
        if (n >= 5) {
            sig.macd_histogram_slope = static_cast<float>(linear_slope(hist, last, 5));
        }

        sig.macd_zero_position = (dif[last] >= 0.0) ? +1 : -1;
    }

    // ── RSI (14, Wilder's smoothing) ──────────────────────────────────────
    {
        constexpr int RSI_PERIOD = 14;
        std::vector<double> gains(n, 0.0), losses(n, 0.0);
        for (int i = 1; i < n; ++i) {
            double chg = closes[i] - closes[i - 1];
            gains[i]  = (chg > 0) ? chg : 0.0;
            losses[i] = (chg < 0) ? -chg : 0.0;
        }
        auto avg_gain = wilder_ema(gains, RSI_PERIOD);
        auto avg_loss = wilder_ema(losses, RSI_PERIOD);

        std::vector<double> rsi_series(n, 50.0);
        for (int i = 0; i < n; ++i) {
            if (avg_loss[i] < 1e-10) {
                rsi_series[i] = (avg_gain[i] < 1e-10) ? 50.0 : 100.0;
            } else {
                double rs = avg_gain[i] / avg_loss[i];
                rsi_series[i] = 100.0 - 100.0 / (1.0 + rs);
            }
        }

        double rval = rsi_series[last];
        sig.rsi_14  = static_cast<float>(rval);
        sig.rsi_zone = (rval < 30.0) ? 0 : (rval > 70.0) ? 2 : 1;
        sig.rsi_divergence = static_cast<float>(divergence_signal(closes, rsi_series, last));
    }

    // ── Bollinger Bands (20-period, 2σ) ───────────────────────────────────
    {
        constexpr int BB_PERIOD = 20;
        if (n >= BB_PERIOD) {
            double ma = rolling_avg(closes, last, BB_PERIOD);
            double sd = rolling_std_val(closes, last, BB_PERIOD);
            double upper = ma + 2.0 * sd;
            double lower = ma - 2.0 * sd;
            double band_width = 4.0 * sd;  // upper - lower

            // Position: -1 at lower, 0 at mid, +1 at upper
            if (band_width > 1e-10) {
                sig.bb_position = static_cast<float>(
                    (closes[last] - lower) / band_width * 2.0 - 1.0);
            }

            // Width change: compare current width to 20d avg width
            // Compute rolling width for each bar
            std::vector<double> widths(n, 0.0);
            for (int i = BB_PERIOD - 1; i < n; ++i) {
                double sd_i = rolling_std_val(closes, i, BB_PERIOD);
                widths[i] = 4.0 * sd_i;
            }
            double avg_width = rolling_avg(widths, last, BB_PERIOD);
            if (avg_width > 1e-10) {
                sig.bb_width_change = static_cast<float>(
                    (band_width - avg_width) / avg_width);
            }
        }
    }

    // ── Volume-Price sync (20d) ────────────────────────────────────────────
    {
        constexpr int VP_WINDOW = 20;
        if (n >= VP_WINDOW + 1) {
            int sync_count = 0;
            int start = last - VP_WINDOW + 1;
            for (int i = start; i <= last; ++i) {
                if (i == 0) continue;
                double price_chg = closes[i] - closes[i - 1];
                double vol_chg   = volumes[i] - volumes[i - 1];
                if ((price_chg > 0 && vol_chg > 0) || (price_chg < 0 && vol_chg < 0)) {
                    ++sync_count;
                }
            }
            sig.volume_price_sync = static_cast<float>(
                sync_count / static_cast<double>(VP_WINDOW));
        }
    }

    // ── Volume breakout ───────────────────────────────────────────────────
    {
        constexpr int VB_WINDOW = 20;
        if (n >= VB_WINDOW) {
            double avg_vol = rolling_avg(volumes, last - 1, VB_WINDOW);  // exclude today
            if (avg_vol > 1e-10) {
                sig.volume_breakout = static_cast<float>(volumes[last] / avg_vol);
            }
        }
    }

    // ── OBV slope (5d) ────────────────────────────────────────────────────
    {
        std::vector<double> obv(n, 0.0);
        for (int i = 1; i < n; ++i) {
            double chg = closes[i] - closes[i - 1];
            if (chg > 0)       obv[i] = obv[i - 1] + volumes[i];
            else if (chg < 0)  obv[i] = obv[i - 1] - volumes[i];
            else               obv[i] = obv[i - 1];
        }
        if (n >= 5) {
            sig.obv_slope = static_cast<float>(linear_slope(obv, last, 5));
        }
    }

    // ── Momentum ──────────────────────────────────────────────────────────
    {
        if (last >= 20 && closes[last - 20] > 1e-10) {
            sig.momentum_20d = static_cast<float>(
                (closes[last] - closes[last - 20]) / closes[last - 20]);
        }
        if (last >= 60 && closes[last - 60] > 1e-10) {
            sig.momentum_60d = static_cast<float>(
                (closes[last] - closes[last - 60]) / closes[last - 60]);
        }
    }

    // ── MA trend alignment ────────────────────────────────────────────────
    {
        if (n >= 60) {
            double ma5  = rolling_avg(closes, last, 5);
            double ma20 = rolling_avg(closes, last, 20);
            double ma60 = rolling_avg(closes, last, 60);
            if (ma5 > ma20 && ma20 > ma60)       sig.ma_trend =  1.0f;
            else if (ma5 < ma20 && ma20 < ma60)  sig.ma_trend = -1.0f;
            else                                  sig.ma_trend =  0.0f;
        }
    }

    // ── Volatility (annualized 20d realized vol) ──────────────────────────
    {
        constexpr int VOL_WINDOW = 20;
        if (n >= VOL_WINDOW + 1) {
            std::vector<double> log_rets;
            log_rets.reserve(VOL_WINDOW);
            for (int i = last - VOL_WINDOW + 1; i <= last; ++i) {
                if (closes[i - 1] > 1e-10) {
                    log_rets.push_back(std::log(closes[i] / closes[i - 1]));
                }
            }
            if (!log_rets.empty()) {
                double mean = std::accumulate(log_rets.begin(), log_rets.end(), 0.0)
                              / log_rets.size();
                double var = 0.0;
                for (double r : log_rets) {
                    double d = r - mean;
                    var += d * d;
                }
                double daily_std = std::sqrt(var / std::max<size_t>(1, log_rets.size() - 1));
                sig.volatility_20d = static_cast<float>(daily_std * std::sqrt(252.0));
            }
        }
    }

    // ── Liquidity (avg daily turnover rate, 20d) ──────────────────────────
    {
        constexpr int LIQ_WINDOW = 20;
        if (n >= LIQ_WINDOW) {
            sig.liquidity_20d = static_cast<float>(
                rolling_avg(turnover_rates, last, LIQ_WINDOW));
        }
    }

    return sig;
}

// ---------------------------------------------------------------------------
// Rolling signal series
// ---------------------------------------------------------------------------

std::unordered_map<std::string, TechnicalSignal> compute_signal_series(
    const std::vector<Bar>& bars,
    int warmup_bars)
{
    std::unordered_map<std::string, TechnicalSignal> result;
    int n = static_cast<int>(bars.size());
    for (int end = warmup_bars; end <= n; ++end) {
        std::vector<Bar> window(bars.begin(), bars.begin() + end);
        TechnicalSignal sig = compute_signals(window);
        result[bar_date_str(bars[end - 1])] = sig;
    }
    return result;
}

} // namespace trade
