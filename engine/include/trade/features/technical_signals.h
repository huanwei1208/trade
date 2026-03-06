#pragma once

#include "trade/model/bar.h"
#include <unordered_map>
#include <string>
#include <vector>

namespace trade {

// Extracted technical signals for a single bar (T-1 snapshot).
// Each field has a documented economic meaning for event-driven ML features.
struct TechnicalSignal {
    // --- KDJ (Stochastic) ---
    int kdj_zone = 1;          // 0=oversold(<20), 1=neutral, 2=overbought(>80)
    int kdj_cross = 0;         // +1=golden cross (K>D, was K<D), -1=death cross, 0=none
    float kdj_divergence = 0;  // price new high but K not new high => negative divergence [-1,0,+1]

    // --- MACD ---
    int macd_cross = 0;              // +1=golden cross, -1=death cross, 0=none
    float macd_histogram_slope = 0;  // slope of MACD histogram (positive=accelerating)
    int macd_zero_position = 0;      // +1=DIF above zero, -1=below

    // --- RSI (14-period Wilder's) ---
    float rsi_14 = 50.0f;
    int rsi_zone = 1;          // 0=oversold(<30), 1=neutral, 2=overbought(>70)
    float rsi_divergence = 0;  // price new high but RSI not new high => negative [-1,0,+1]

    // --- Bollinger Bands (20-period) ---
    float bb_position = 0;      // -1=at lower band, 0=at middle, +1=at upper band
    float bb_width_change = 0;  // (current_width - avg_width) / avg_width, positive=expanding

    // --- Volume-Price ---
    float volume_price_sync = 0;  // sign(price_change) == sign(volume_change) over 20d (ratio)
    float volume_breakout = 0;    // current volume / 20d avg volume
    float obv_slope = 0;          // OBV 5d linear slope (positive=accumulation)

    // --- Momentum / Trend ---
    float momentum_20d = 0;   // (close - close_20d_ago) / close_20d_ago
    float momentum_60d = 0;   // (close - close_60d_ago) / close_60d_ago
    float ma_trend = 0;       // +1=bullish alignment (ma5>ma20>ma60), -1=bearish, 0=mixed
    float volatility_20d = 0; // annualized 20d realized volatility (std of daily log returns * sqrt(252))

    // --- Derived / Market microstructure ---
    float liquidity_20d = 0;  // average daily turnover rate over last 20d
};

// Compute technical signals from a sorted bar series (ascending date).
// Returns the signal snapshot for the LAST bar in the series.
// Requires at least 60 bars for full signal population; with fewer bars
// only the fields that can be computed are filled (others stay at default).
TechnicalSignal compute_signals(const std::vector<Bar>& bars);

// Compute signals for every bar in a rolling window and return a map
// from ISO date string ("YYYY-MM-DD") to signal snapshot.
// Useful for building feature datasets.
// bars must be sorted ascending by date.
// warmup_bars: minimum bars required before the first entry is generated
//   (default 60).
std::unordered_map<std::string, TechnicalSignal> compute_signal_series(
    const std::vector<Bar>& bars,
    int warmup_bars = 60);

} // namespace trade
