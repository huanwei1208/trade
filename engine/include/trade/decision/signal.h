#pragma once

#include "trade/common/types.h"

#include <string>
#include <vector>

namespace trade {

// ============================================================================
// Signal: combined alpha signal for a single symbol
// ============================================================================
// The Signal struct is the output of the signal combination pipeline.  It
// carries the fused alpha score, per-model breakdowns, and the sentiment
// overlay that may gate or modify the final trading decision.
//
// Usage:
//   SignalCombiner combiner;
//   Signal sig = combiner.combine(calibrated, regime, weights);
//   if (sig.confidence >= 0.6 && !sig.is_conflict) {
//       // eligible for trade list
//   }
//

struct Signal {
    Symbol symbol;
    double alpha_score = 0.0;       // combined alpha signal (weighted mean)
    double confidence = 0.0;        // [0, 1]; minimum 0.6 for trading
    Regime regime = Regime::kBull;   // current market regime at signal time
    bool is_conflict = false;        // models disagree -> watchlist, not trade

    // -----------------------------------------------------------------------
    // Per-model score breakdown
    // -----------------------------------------------------------------------
    struct ModelScore {
        std::string model_name;
        double raw_score = 0.0;          // original model output
        double calibrated_score = 0.0;   // after z-score + logistic mapping
        double weight = 0.0;             // contribution weight in fusion
    };
    std::vector<ModelScore> model_scores;

    // -----------------------------------------------------------------------
    // Sentiment overlay (from NLP / news pipeline)
    // -----------------------------------------------------------------------
    struct SentimentOverlay {
        std::string stock_mood;   // "偏多", "中性", "偏空"
        bool neg_shock = false;   // sudden negative event detected
        std::string key_news;     // headline / summary triggering the mood
    };
    SentimentOverlay sentiment;

    // -----------------------------------------------------------------------
    // Convenience helpers
    // -----------------------------------------------------------------------

    // Is the signal eligible for the trade list (not conflict, meets threshold)?
    bool is_tradable() const {
        return !is_conflict && confidence >= 0.6;
    }

    // Is there a negative sentiment shock?
    bool has_neg_shock() const { return sentiment.neg_shock; }

    // Number of models contributing to this signal
    size_t num_models() const { return model_scores.size(); }
};

} // namespace trade
