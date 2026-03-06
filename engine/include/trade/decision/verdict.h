#pragma once

#include "trade/common/types.h"

#include <nlohmann/json.hpp>
#include <string>
#include <vector>

namespace trade {

// ============================================================================
// Verdict: structured prediction output for a single stock
// ============================================================================
//
// Produced by cmd_predict and serialised to JSON for consumption by the Python
// Streamlit UI (via cpp_bridge.py).
//
// JSON schema:
//   {
//     "symbol":              "600036.SH",
//     "date":                "2026-03-01",
//     "close":               12.34,
//     "probability":         0.043,          // predicted 5d return (raw)
//     "bull_prob":           0.72,           // P(return > 0) estimate
//     "direction":           "UP",
//     "action_condition":    "...",
//     "window_score":        68,
//     "supporting_evidence": ["...", "..."],
//     "opposing_evidence":   ["...", "..."],
//     "devils_advocate":     "...",
//     "annual_vol":          0.34
//   }
//
struct Verdict {
    Symbol      symbol;
    std::string date;                      // ISO: "YYYY-MM-DD"
    double      close            = 0.0;
    double      probability      = 0.0;    // raw predicted 5d return (can be negative)
    double      bull_prob        = 0.5;    // P(up) ∈ [0, 1]
    std::string direction        = "NEUTRAL";
    std::string action_condition;
    int         window_score     = 0;
    std::vector<std::string> supporting_evidence;
    std::vector<std::string> opposing_evidence;
    std::string devils_advocate;
    double      annual_vol       = 0.0;

    // Serialise to nlohmann::json
    nlohmann::json to_json() const {
        return nlohmann::json{
            {"symbol",              symbol},
            {"date",                date},
            {"close",               close},
            {"probability",         probability},
            {"bull_prob",           bull_prob},
            {"direction",           direction},
            {"action_condition",    action_condition},
            {"window_score",        window_score},
            {"supporting_evidence", supporting_evidence},
            {"opposing_evidence",   opposing_evidence},
            {"devils_advocate",     devils_advocate},
            {"annual_vol",          annual_vol},
        };
    }
};

// ============================================================================
// RiskVerdict: structured risk output for a single stock
// ============================================================================
//
// JSON schema:
//   {
//     "symbol":        "600036.SH",
//     "period_start":  "2024-01-01",
//     "period_end":    "2026-03-01",
//     "daily_vol":     0.014,
//     "annual_vol":    0.22,
//     "var_99_hist":   0.031,
//     "var_99_param":  0.034,
//     "cvar_99":       0.042,
//     "max_drawdown":  0.18,
//     "quarter_kelly": 0.12
//   }
//
struct RiskVerdict {
    Symbol      symbol;
    std::string period_start;
    std::string period_end;
    double      daily_vol     = 0.0;
    double      annual_vol    = 0.0;
    double      var_99_hist   = 0.0;
    double      var_99_param  = 0.0;
    double      cvar_99       = 0.0;
    double      max_drawdown  = 0.0;
    double      quarter_kelly = 0.0;

    nlohmann::json to_json() const {
        return nlohmann::json{
            {"symbol",        symbol},
            {"period_start",  period_start},
            {"period_end",    period_end},
            {"daily_vol",     daily_vol},
            {"annual_vol",    annual_vol},
            {"var_99_hist",   var_99_hist},
            {"var_99_param",  var_99_param},
            {"cvar_99",       cvar_99},
            {"max_drawdown",  max_drawdown},
            {"quarter_kelly", quarter_kelly},
        };
    }
};

} // namespace trade
