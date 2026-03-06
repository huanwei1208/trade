#include "trade/cli/commands.h"

#include "trade/cli/shared.h"
#include "trade/common/time_utils.h"
#include "trade/regime/regime_detector.h"
#include "trade/risk/kelly.h"

#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <vector>

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

namespace trade::cli {
int cmd_report(const CliArgs& args, const trade::Config& config) {
    if (args.symbol.empty()) { spdlog::error("--symbol required"); return 1; }
    auto bars = load_bars(args.symbol, config);
    if (bars.size() < 60) { spdlog::error("Need >=60 bars"); return 1; }

    std::vector<double> rets;
    for (size_t i = 1; i < bars.size(); ++i)
        if (bars[i - 1].close > 0)
            rets.push_back((bars[i].close - bars[i - 1].close) / bars[i - 1].close);

    double mr = 0, vol = 0;
    for (double r : rets) mr += r;
    mr /= rets.size();
    for (double r : rets) vol += (r - mr) * (r - mr);
    vol = std::sqrt(vol / rets.size());

    Eigen::VectorXd mu_vec(1); mu_vec(0) = mr;
    Eigen::VectorXd sigma_vec(1); sigma_vec(0) = vol;
    Eigen::VectorXd conf_vec(1); conf_vec(0) = 1.0;

    trade::KellyCalculator kelly;
    auto k = kelly.compute_diagnostics(mu_vec, sigma_vec, conf_vec);

    trade::RegimeDetector detector;
    std::vector<double> prices;
    for (const auto& b : bars) prices.push_back(b.close);
    trade::RegimeDetector::MarketBreadth breadth;
    breadth.total_stocks = 2500;
    breadth.up_stocks = 1500;
    auto regime = detector.update(prices, breadth);

    std::string regime_str = regime.regime_name();

    double full_kelly_val = k.raw_kelly.size() > 0 ? k.raw_kelly(0) : 0.0;
    double quarter_kelly_val = k.final_weights.size() > 0 ? k.final_weights(0) : 0.0;

    nlohmann::json rpt;
    rpt["ticker"]    = args.symbol;
    rpt["date"]      = trade::format_date(bars.back().date);
    rpt["close"]     = bars.back().close;
    rpt["regime"]    = regime_str;
    rpt["risk"] = {
        {"daily_vol", vol}, {"annual_vol", vol * std::sqrt(252)},
        {"mean_daily_return", mr},
        {"full_kelly", full_kelly_val}, {"quarter_kelly", quarter_kelly_val}
    };
    rpt["recommendation"] = {
        {"suggested_weight", quarter_kelly_val},
        {"confidence", 0.6}, {"regime", regime_str}
    };

    std::cout << "=== Report: " << args.symbol << " ===\n\n"
              << rpt.dump(2) << std::endl;

    if (!args.output.empty()) {
        std::ofstream ofs(args.output);
        ofs << rpt.dump(2) << std::endl;
        spdlog::info("Saved to {}", args.output);
    }
    return 0;
}
} // namespace trade::cli
