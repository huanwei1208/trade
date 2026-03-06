#include "trade/decision/decision_report.h"
#include "trade/common/time_utils.h"

#include <chrono>
#include <cstdio>
#include <ctime>
#include <fstream>

namespace trade {

nlohmann::json DecisionReporter::generate_position_report(
    const Signal& signal,
    const PositionRisk& risk,
    const ExitPlan& exit_plan,
    const std::string& action,
    const std::string& entry_reason,
    const std::vector<std::string>& invalidators) const {

    nlohmann::json report;
    report["ticker"] = signal.symbol;
    report["action"] = action;
    report["target_weight"] = risk.target_weight;
    report["current_weight"] = risk.current_weight;
    report["alpha_score"] = signal.alpha_score;
    report["confidence"] = signal.confidence;
    report["regime"] = regime_to_string(signal.regime);
    report["risk_contribution"] = risk.risk_contribution;
    report["marginal_var"] = risk.marginal_var;
    report["liquidity_days"] = risk.liquidity_days;
    report["entry_reason"] = entry_reason;
    report["invalidators"] = invalidators;

    // Exit plan
    nlohmann::json exit_json;
    exit_json["time_stop_days"] = exit_plan.time_stop_days;
    exit_json["signal_stop"] = exit_plan.signal_stop;
    exit_json["risk_stop_pct"] = exit_plan.risk_stop_pct;
    exit_json["take_profit_pct"] = exit_plan.take_profit_pct;
    report["exit_plan"] = exit_json;

    // Sentiment overlay
    nlohmann::json sent_json;
    sent_json["stock_mood"] = signal.sentiment.stock_mood;
    sent_json["neg_shock"] = signal.sentiment.neg_shock;
    sent_json["key_news"] = signal.sentiment.key_news;
    report["sentiment"] = sent_json;

    // Model scores breakdown
    nlohmann::json model_scores = nlohmann::json::array();
    for (const auto& ms : signal.model_scores) {
        nlohmann::json ms_json;
        ms_json["model_name"] = ms.model_name;
        ms_json["raw_score"] = ms.raw_score;
        ms_json["calibrated_score"] = ms.calibrated_score;
        ms_json["weight"] = ms.weight;
        model_scores.push_back(ms_json);
    }
    report["model_scores"] = model_scores;

    return report;
}

nlohmann::json DecisionReporter::generate_portfolio_report(
    const RiskDashboard& dashboard) const {

    nlohmann::json report;
    report["gross_exposure"] = dashboard.gross_exposure;
    report["net_exposure"] = dashboard.net_exposure;
    report["cash"] = dashboard.cash_weight;

    // Sector breakdown
    nlohmann::json sectors;
    for (const auto& [sector, weight] : dashboard.sector_breakdown) {
        sectors[sector] = weight;
    }
    report["sector_breakdown"] = sectors;

    // Style exposure
    nlohmann::json style;
    for (const auto& [factor, zscore] : dashboard.style_exposure) {
        style[factor] = zscore;
    }
    report["style_exposure"] = style;

    // Risk metrics
    report["ex_ante_return"] = dashboard.ex_ante_return;
    report["var_99_1d"] = dashboard.var_99_1d;
    report["cvar_99_1d"] = dashboard.cvar_99_1d;

    // Stress tests
    report["stress_loss_2015_crash"] = dashboard.stress_loss_2015_crash;
    report["stress_loss_2018_trade_war"] = dashboard.stress_loss_2018_trade_war;
    report["stress_loss_covid_2020"] = dashboard.stress_loss_covid_2020;

    // Top risk contributors
    nlohmann::json contributors = nlohmann::json::array();
    for (const auto& [sym, contrib] : dashboard.top_risk_contributors) {
        contributors.push_back(nlohmann::json::array({sym, contrib}));
    }
    report["top_risk_contributors"] = contributors;

    report["constraint_violations"] = dashboard.constraint_violations;
    report["market_regime"] = regime_to_string(dashboard.market_regime);
    report["market_sentiment"] = dashboard.market_sentiment;

    return report;
}

nlohmann::json DecisionReporter::generate_full_report(
    const PortfolioSnapshot& portfolio,
    const RiskDashboard& dashboard,
    const std::unordered_map<Symbol, std::string>& actions,
    const std::unordered_map<Symbol, std::string>& entry_reasons,
    const std::unordered_map<Symbol, std::vector<std::string>>& invalidators) const {

    nlohmann::json report;

    // Format report date from portfolio snapshot date (YYYY-MM-DD)
    report["report_date"] = format_date(portfolio.date);

    // Format generated_at as current wall-clock time (YYYY-MM-DDTHH:MM:SS)
    auto now = std::chrono::system_clock::now();
    auto time_t_now = std::chrono::system_clock::to_time_t(now);
    std::tm tm_now = *std::localtime(&time_t_now);
    char ts_buf[20];
    std::snprintf(ts_buf, sizeof(ts_buf), "%04d-%02d-%02dT%02d:%02d:%02d",
                  tm_now.tm_year + 1900, tm_now.tm_mon + 1, tm_now.tm_mday,
                  tm_now.tm_hour, tm_now.tm_min, tm_now.tm_sec);
    report["generated_at"] = std::string(ts_buf);

    // Portfolio summary
    report["portfolio_summary"] = generate_portfolio_report(dashboard);

    // Per-position reports
    nlohmann::json positions = nlohmann::json::array();
    for (const auto& sym : portfolio.symbols) {
        // Look up signal
        Signal signal;
        auto sig_it = portfolio.signals.find(sym);
        if (sig_it != portfolio.signals.end()) {
            signal = sig_it->second;
        } else {
            signal.symbol = sym;
        }

        // Look up risk
        PositionRisk risk;
        auto risk_it = portfolio.position_risks.find(sym);
        if (risk_it != portfolio.position_risks.end()) {
            risk = risk_it->second;
        }

        // Look up exit plan
        ExitPlan exit_plan;
        auto exit_it = portfolio.exit_plans.find(sym);
        if (exit_it != portfolio.exit_plans.end()) {
            exit_plan = exit_it->second;
        }

        // Look up action
        std::string action = "hold";
        auto act_it = actions.find(sym);
        if (act_it != actions.end()) {
            action = act_it->second;
        }

        // Look up entry reason
        std::string reason;
        auto reas_it = entry_reasons.find(sym);
        if (reas_it != entry_reasons.end()) {
            reason = reas_it->second;
        }

        // Look up invalidators
        std::vector<std::string> inv;
        auto inv_it = invalidators.find(sym);
        if (inv_it != invalidators.end()) {
            inv = inv_it->second;
        }

        positions.push_back(
            generate_position_report(signal, risk, exit_plan, action, reason, inv));
    }
    report["positions"] = positions;

    return report;
}

void DecisionReporter::write_to_file(const nlohmann::json& report,
                                      const std::string& path) {
    std::ofstream file(path);
    if (file.is_open()) {
        file << report.dump(2);
    }
}

std::string DecisionReporter::regime_to_string(Regime r) {
    switch (r) {
        case Regime::kBull: return "bull";
        case Regime::kBear: return "bear";
        case Regime::kShock: return "shock";
    }
    return "unknown";
}

std::string DecisionReporter::side_to_string(Side s) {
    switch (s) {
        case Side::kBuy: return "buy";
        case Side::kSell: return "sell";
    }
    return "unknown";
}

} // namespace trade
