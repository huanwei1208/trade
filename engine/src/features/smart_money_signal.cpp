#include "trade/features/smart_money_signal.h"
#include <cmath>
#include <limits>

namespace trade {

// ============================================================================
// money_flow_multiplier
// ============================================================================
// MFM = ((close - low) - (high - close)) / (high - low)
//     = (2*close - high - low) / (high - low)
// Returns NaN when high == low (doji / zero-range bar).

Eigen::VectorXd SmartMoneyCalculator::money_flow_multiplier(
    const Eigen::VectorXd& high,
    const Eigen::VectorXd& low,
    const Eigen::VectorXd& close)
{
    int n = static_cast<int>(high.size());
    Eigen::VectorXd mfm(n);
    mfm.setConstant(std::numeric_limits<double>::quiet_NaN());

    for (int i = 0; i < n; ++i) {
        double range = high(i) - low(i);
        if (range > 1e-8) {
            mfm(i) = (2.0 * close(i) - high(i) - low(i)) / range;
        }
    }
    return mfm;
}

// ============================================================================
// chaikin_money_flow
// ============================================================================
// CMF(n) = sum_{t-n+1..t}(MFM × vol) / sum_{t-n+1..t}(vol)
// Returns NaN when cumulative volume in the window is zero.

Eigen::VectorXd SmartMoneyCalculator::chaikin_money_flow(
    const Eigen::VectorXd& mfm,
    const Eigen::VectorXd& vol,
    int window)
{
    int n = static_cast<int>(mfm.size());
    Eigen::VectorXd cmf(n);
    cmf.setConstant(std::numeric_limits<double>::quiet_NaN());

    for (int i = window - 1; i < n; ++i) {
        double mfv_sum = 0.0;
        double vol_sum = 0.0;
        bool has_nan = false;
        for (int j = i - window + 1; j <= i; ++j) {
            if (std::isnan(mfm(j))) { has_nan = true; break; }
            mfv_sum += mfm(j) * vol(j);
            vol_sum += vol(j);
        }
        if (!has_nan && vol_sum > 1e-8) {
            cmf(i) = mfv_sum / vol_sum;
        }
    }
    return cmf;
}

// ============================================================================
// compute
// ============================================================================

FeatureSet SmartMoneyCalculator::compute(
    const std::vector<BarSeries>& series,
    const std::unordered_map<Symbol, Instrument>& /*instruments*/) const
{
    if (series.empty()) return {};

    int n_stocks = static_cast<int>(series.size());

    constexpr int n_features = 2;
    const std::vector<std::string> feat_names = {
        "smart_money_flow_5d",   // 0
        "smart_money_flow_20d",  // 1
    };

    Eigen::MatrixXd mat(n_stocks, n_features);
    mat.setConstant(std::numeric_limits<double>::quiet_NaN());

    std::vector<Symbol> symbols;
    std::vector<Date>   dates;

    auto last = [](const Eigen::VectorXd& v) -> double {
        return v.size() > 0 ? v(v.size() - 1)
                            : std::numeric_limits<double>::quiet_NaN();
    };

    for (int s = 0; s < n_stocks; ++s) {
        const auto& bs = series[s];
        symbols.push_back(bs.symbol);
        dates.push_back(bs.empty() ? Date{} : bs.bars.back().date);

        int n = static_cast<int>(bs.size());
        if (n < 5) continue;

        // Extract OHLCV vectors
        Eigen::VectorXd high_v(n), low_v(n), close_v(n), vol_v(n);
        for (int i = 0; i < n; ++i) {
            high_v(i)  = bs[i].high;
            low_v(i)   = bs[i].low;
            close_v(i) = bs[i].close;
            vol_v(i)   = static_cast<double>(bs[i].volume);
        }

        auto mfm = money_flow_multiplier(high_v, low_v, close_v);

        mat(s, 0) = last(chaikin_money_flow(mfm, vol_v, 5));
        if (n >= 20) {
            mat(s, 1) = last(chaikin_money_flow(mfm, vol_v, 20));
        }
    }

    FeatureSet fs;
    fs.names   = feat_names;
    fs.symbols = std::move(symbols);
    fs.dates   = std::move(dates);
    fs.matrix  = std::move(mat);
    return fs;
}

} // namespace trade
