#pragma once

#include "trade/common/types.h"

#include <Eigen/Dense>
#include <algorithm>
#include <cmath>
#include <string>
#include <unordered_map>
#include <vector>

namespace trade {

// ============================================================================
// DrawdownController: systematic drawdown control and deleveraging
// ============================================================================
//
// Three mechanisms:
//
// A) Automatic deleveraging ladder (based on peak-to-trough drawdown):
//      >= 5%  : freeze high-beta new entries, reduce exposure 10%
//      >= 8%  : reduce exposure 20%, cut lowest-confidence quartile
//      >= 12% : reduce exposure 40%, single-stock cap drops to 5%
//      >= 15% : capital preservation mode -- only close or hedge
//
// B) Volatility scaling:
//      scale = min(1.0, target_vol / realized_vol_20d)
//      floor at 0.5 to avoid excessive deleveraging in transient spikes.
//
// C) Limit-down lock handling (A-share specific):
//      - Each stock gets a lock probability score (0-1).
//      - High-score stocks have their position cap halved.
//      - At least 10% cash buffer is forced when any position is locked.
//
class DrawdownController {
public:
    // -----------------------------------------------------------------------
    // Drawdown ladder levels
    // -----------------------------------------------------------------------
    enum class DrawdownLevel : uint8_t {
        kNormal = 0,        // dd < 5%
        kLevel1 = 1,        // dd >= 5%
        kLevel2 = 2,        // dd >= 8%
        kLevel3 = 3,        // dd >= 12%
        kCapitalPreserve = 4 // dd >= 15%
    };

    struct Config {
        // Drawdown thresholds
        double level1_threshold = 0.05;    // 5%
        double level2_threshold = 0.08;    // 8%
        double level3_threshold = 0.12;    // 12%
        double capital_preserve_threshold = 0.15; // 15%

        // Exposure reduction at each level
        double level1_reduction = 0.10;    // reduce by 10%
        double level2_reduction = 0.20;    // reduce by 20%
        double level3_reduction = 0.40;    // reduce by 40%

        // Level 3 overrides
        double level3_single_stock_cap = 0.05;

        // Volatility scaling
        double target_vol = 0.15;          // 15% annualised
        double vol_scale_floor = 0.50;     // minimum scale factor
        int realized_vol_window = 20;      // 20 trading days

        // Lock handling
        double lock_prob_threshold = 0.5;  // threshold to halve cap
        double min_cash_buffer = 0.10;     // 10% cash on any lock
        double lock_cap_reduction = 0.50;  // halve position cap

        // Beta threshold for "high-beta" in level 1
        double high_beta_threshold = 1.3;
    };

    // -----------------------------------------------------------------------
    // Per-stock lock probability input
    // -----------------------------------------------------------------------
    struct LockInfo {
        Symbol symbol;
        double lock_probability = 0.0;     // [0, 1] probability of limit-down lock
        bool is_locked = false;            // currently locked / suspended
        bool is_suspended = false;
    };

    // -----------------------------------------------------------------------
    // Drawdown control output
    // -----------------------------------------------------------------------
    struct DrawdownAction {
        DrawdownLevel level = DrawdownLevel::kNormal;
        double current_drawdown = 0.0;     // peak-to-trough as fraction
        double nav_peak = 0.0;
        double nav_current = 0.0;

        // Exposure adjustments
        double target_exposure_multiplier = 1.0;  // multiply existing weights
        double vol_scale = 1.0;                    // volatility scaling factor
        double effective_multiplier = 1.0;         // min of above two

        // Specific actions
        bool freeze_high_beta_new = false;
        bool cut_lowest_confidence_quartile = false;
        double single_stock_cap = 0.10;    // overridden at Level 3
        bool capital_preservation_mode = false;

        // Lock-related
        double required_cash_buffer = 0.0;
        int high_lock_prob_count = 0;
        std::vector<Symbol> locked_symbols;
    };

    // -----------------------------------------------------------------------
    // Volatility scaling result
    // -----------------------------------------------------------------------
    struct VolScaling {
        double realized_vol_20d = 0.0;     // annualised
        double target_vol = 0.0;
        double raw_scale = 1.0;            // target / realized
        double clamped_scale = 1.0;        // max(floor, min(1.0, raw))
    };

    DrawdownController() : config_{} {}
    explicit DrawdownController(Config cfg) : config_(cfg) {}

    // -----------------------------------------------------------------------
    // Core interface
    // -----------------------------------------------------------------------

    // Evaluate the current drawdown level and return required actions.
    //   nav_series: historical NAV series (most recent last)
    //   returns:    recent daily portfolio returns (for vol scaling)
    //   locks:      per-stock lock probability information
    //   betas:      per-stock beta values (for high-beta freeze)
    DrawdownAction evaluate(
        const std::vector<double>& nav_series,
        const std::vector<double>& returns,
        const std::vector<LockInfo>& locks = {},
        const std::unordered_map<Symbol, double>& betas = {}) const;

    // -----------------------------------------------------------------------
    // Sub-components (can be called independently)
    // -----------------------------------------------------------------------

    // Compute drawdown from NAV series
    static double compute_drawdown(const std::vector<double>& nav_series);
    static double compute_peak(const std::vector<double>& nav_series);

    // Classify the drawdown into a level
    DrawdownLevel classify_drawdown(double drawdown) const;

    // Compute the volatility scaling factor
    VolScaling compute_vol_scaling(const std::vector<double>& returns) const;

    // Compute realised volatility (annualised) from daily returns
    static double realized_vol(const std::vector<double>& returns, int window);

    // Adjust weights for drawdown control
    //   weights:     (N,) current portfolio weights
    //   action:      output from evaluate()
    //   confidence:  (N,) model confidence scores (for quartile cut)
    //   betas:       (N,) stock betas (for high-beta freeze check)
    Eigen::VectorXd adjust_weights(
        const Eigen::VectorXd& weights,
        const DrawdownAction& action,
        const Eigen::VectorXd& confidence = {},
        const Eigen::VectorXd& betas = {}) const;

    // Apply lock-related adjustments to weights
    Eigen::VectorXd apply_lock_adjustments(
        const Eigen::VectorXd& weights,
        const std::vector<LockInfo>& locks,
        double single_stock_cap) const;

    const Config& config() const { return config_; }
    void set_config(const Config& c) { config_ = c; }

private:
    Config config_;
};

} // namespace trade
