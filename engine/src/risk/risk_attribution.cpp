#include "trade/risk/risk_attribution.h"

#include <algorithm>
#include <cmath>
#include <unordered_map>

namespace trade {

RiskAttribution::RiskDecomposition RiskAttribution::decompose(
    const Eigen::VectorXd& weights,
    const Eigen::MatrixXd& covariance,
    const Eigen::MatrixXd& factor_loadings,
    const Eigen::MatrixXd& factor_cov,
    const Eigen::VectorXd& idio_var,
    const std::vector<Symbol>& symbols,
    const std::vector<SWIndustry>& industries,
    const std::vector<std::string>& factor_names,
    const Eigen::VectorXd& adv) const {

    RiskDecomposition result;
    int n = static_cast<int>(weights.size());
    if (n == 0) return result;

    // Total portfolio variance: w' * Sigma * w
    result.total_variance = weights.transpose() * covariance * weights;
    result.total_vol = std::sqrt(result.total_variance * 252.0);

    // 99% parametric VaR (z_0.99 = 2.326)
    result.total_var_99 = 2.326 * std::sqrt(result.total_variance);

    // Factor vs idiosyncratic decomposition
    if (factor_loadings.rows() == n && factor_cov.rows() > 0) {
        // Factor variance: w' * B * Sigma_f * B' * w
        Eigen::VectorXd Bw = factor_loadings.transpose() * weights;
        result.factor_variance = Bw.transpose() * factor_cov * Bw;
    }

    if (idio_var.size() == n) {
        // Idiosyncratic variance: w' * D * w  (D diagonal)
        result.idio_variance = 0.0;
        for (int i = 0; i < n; ++i) {
            result.idio_variance += weights(i) * weights(i) * idio_var(i);
        }
    } else {
        result.idio_variance = result.total_variance - result.factor_variance;
    }

    if (result.total_variance > 0.0) {
        result.factor_pct = result.factor_variance / result.total_variance;
        result.idio_pct = result.idio_variance / result.total_variance;
    }

    // Per-stock contributions
    Eigen::VectorXd m_var = marginal_var(weights, covariance, config_.var_confidence);
    Eigen::VectorXd c_var = component_var(weights, covariance, config_.var_confidence);
    double total_cvar = c_var.sum();

    result.by_stock.resize(n);
    for (int i = 0; i < n; ++i) {
        auto& sc = result.by_stock[i];
        sc.symbol = (i < static_cast<int>(symbols.size())) ? symbols[i] : "";
        sc.weight = weights(i);
        sc.marginal_var = m_var(i);
        sc.component_var = c_var(i);
        sc.component_var_pct = (total_cvar != 0.0) ? c_var(i) / total_cvar : 0.0;
    }

    // Top-N risk contributors
    auto sorted = result.by_stock;
    std::sort(sorted.begin(), sorted.end(),
              [](const StockContribution& a, const StockContribution& b) {
                  return std::abs(a.component_var) > std::abs(b.component_var);
              });
    int top_n = std::min(config_.top_n, n);
    result.top5_contributors.assign(sorted.begin(), sorted.begin() + top_n);

    // Industry-level decomposition
    std::vector<std::string> industry_labels(n);
    for (int i = 0; i < n; ++i) {
        int ind = (i < static_cast<int>(industries.size()))
                    ? static_cast<int>(industries[i]) : 255;
        industry_labels[i] = std::to_string(ind);
    }
    result.by_industry = group_by(weights, c_var, symbols, industry_labels);

    // Factor decomposition
    if (factor_loadings.rows() == n && factor_cov.rows() > 0) {
        int k = static_cast<int>(factor_loadings.cols());
        result.by_factor.resize(k);
        Eigen::VectorXd port_loading = factor_loadings.transpose() * weights;

        for (int j = 0; j < k; ++j) {
            auto& fc = result.by_factor[j];
            fc.factor_name = (j < static_cast<int>(factor_names.size()))
                                ? factor_names[j] : ("factor_" + std::to_string(j));
            fc.exposure = port_loading(j);
            // Factor j contribution = port_loading_j * (Sigma_f * port_loading)_j
            Eigen::VectorXd sig_pl = factor_cov * port_loading;
            fc.factor_var_contrib = port_loading(j) * sig_pl(j);
            fc.factor_var_pct = (result.total_variance > 0.0)
                                  ? fc.factor_var_contrib / result.total_variance : 0.0;
        }
    }

    // Liquidity bucket decomposition
    if (adv.size() == n) {
        std::vector<std::string> liq_labels(n);
        for (int i = 0; i < n; ++i) {
            liq_labels[i] = liquidity_bucket_name(adv(i));
        }
        result.by_liquidity_bucket = group_by(weights, c_var, symbols, liq_labels);
    }

    // Diversification ratio
    result.diversification_ratio = diversification_ratio(weights, covariance);

    // Effective number of bets
    double sum_sq = 0.0;
    for (const auto& sc : result.by_stock) {
        sum_sq += sc.component_var_pct * sc.component_var_pct;
    }
    result.effective_bets = (sum_sq > 0.0) ? 1.0 / sum_sq : 0.0;

    return result;
}

RiskAttribution::RiskDecomposition RiskAttribution::decompose_simple(
    const Eigen::VectorXd& weights,
    const Eigen::MatrixXd& covariance,
    const std::vector<Symbol>& symbols,
    const std::vector<SWIndustry>& industries) const {

    int n = static_cast<int>(weights.size());
    Eigen::MatrixXd empty_loadings;
    Eigen::MatrixXd empty_factor_cov;
    Eigen::VectorXd empty_idio;
    std::vector<std::string> empty_factor_names;
    Eigen::VectorXd empty_adv;

    return decompose(weights, covariance, empty_loadings, empty_factor_cov,
                     empty_idio, symbols, industries, empty_factor_names, empty_adv);
}

Eigen::VectorXd RiskAttribution::marginal_var(
    const Eigen::VectorXd& weights,
    const Eigen::MatrixXd& cov,
    double confidence) {

    int n = static_cast<int>(weights.size());
    if (n == 0) return {};

    // z_alpha for confidence level (approximation for common values)
    double z = 2.326;  // 99%
    if (confidence <= 0.95) z = 1.645;
    else if (confidence <= 0.975) z = 1.96;

    double port_var = weights.transpose() * cov * weights;
    double sigma_p = std::sqrt(port_var);
    if (sigma_p <= 0.0) return Eigen::VectorXd::Zero(n);

    // Marginal VaR_i = (Sigma * w)_i / sigma_p * z
    Eigen::VectorXd sigma_w = cov * weights;
    return sigma_w / sigma_p * z;
}

Eigen::VectorXd RiskAttribution::component_var(
    const Eigen::VectorXd& weights,
    const Eigen::MatrixXd& cov,
    double confidence) {

    Eigen::VectorXd m_var = marginal_var(weights, cov, confidence);
    return weights.array() * m_var.array();
}

double RiskAttribution::diversification_ratio(
    const Eigen::VectorXd& weights,
    const Eigen::MatrixXd& cov) {

    int n = static_cast<int>(weights.size());
    if (n == 0) return 0.0;

    double port_var = weights.transpose() * cov * weights;
    double sigma_p = std::sqrt(port_var);
    if (sigma_p <= 0.0) return 0.0;

    // Sum of weighted individual volatilities
    double weighted_vol_sum = 0.0;
    for (int i = 0; i < n; ++i) {
        weighted_vol_sum += std::abs(weights(i)) * std::sqrt(cov(i, i));
    }

    return weighted_vol_sum / sigma_p;
}

std::string RiskAttribution::liquidity_bucket_name(double adv) const {
    if (adv >= config_.liquidity_buckets.high_liquidity_min) return "high";
    if (adv >= config_.liquidity_buckets.mid_liquidity_min) return "mid";
    return "low";
}

std::vector<RiskAttribution::GroupContribution> RiskAttribution::group_by(
    const Eigen::VectorXd& weights,
    const Eigen::VectorXd& component_vars,
    const std::vector<Symbol>& symbols,
    const std::vector<std::string>& group_labels) {

    int n = static_cast<int>(weights.size());
    double total_cvar = component_vars.sum();

    std::unordered_map<std::string, GroupContribution> groups;
    for (int i = 0; i < n; ++i) {
        std::string label = (i < static_cast<int>(group_labels.size()))
                              ? group_labels[i] : "unknown";
        auto& g = groups[label];
        g.group_name = label;
        g.total_weight += weights(i);
        g.component_var += component_vars(i);
        g.num_stocks++;
        if (i < static_cast<int>(symbols.size())) {
            g.members.push_back(symbols[i]);
        }
    }

    std::vector<GroupContribution> result;
    result.reserve(groups.size());
    for (auto& [name, g] : groups) {
        g.component_var_pct = (total_cvar != 0.0) ? g.component_var / total_cvar : 0.0;
        result.push_back(std::move(g));
    }

    // Sort by component_var descending
    std::sort(result.begin(), result.end(),
              [](const GroupContribution& a, const GroupContribution& b) {
                  return std::abs(a.component_var) > std::abs(b.component_var);
              });

    return result;
}

} // namespace trade
