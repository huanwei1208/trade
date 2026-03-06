#include "trade/signal/propagation.h"
#include <algorithm>
#include <deque>
#include <fstream>
#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>
#include <unordered_map>

namespace trade {

bool EventPropagator::load(const std::string& json_path) {
    std::ifstream f(json_path);
    if (!f.is_open()) {
        spdlog::warn("EventPropagator: cannot open {}", json_path);
        return false;
    }

    nlohmann::json doc;
    try {
        f >> doc;
    } catch (const std::exception& e) {
        spdlog::error("EventPropagator: JSON parse error: {}", e.what());
        return false;
    }

    nodes_.clear();
    edges_.clear();
    id_to_sw_.clear();
    event_map_.clear();
    adj_.clear();

    // Parse nodes
    if (doc.contains("nodes") && doc["nodes"].is_array()) {
        for (const auto& n : doc["nodes"]) {
            Node node;
            node.id      = n.value("id", "");
            node.sw_code = static_cast<SWIndustry>(n.value("sw_code", 255));
            node.name_zh = n.value("name_zh", "");
            nodes_.push_back(node);
            id_to_sw_[node.id] = node.sw_code;
        }
    }

    // Parse edges and build adjacency list
    if (doc.contains("edges") && doc["edges"].is_array()) {
        for (const auto& e : doc["edges"]) {
            Edge edge;
            edge.source_id    = e.value("source", "");
            edge.target_id    = e.value("target", "");
            edge.relation     = e.value("relation", "");
            edge.weight       = static_cast<float>(e.value("weight", 0.0));
            edge.direction    = e.value("direction", 1);
            edge.typical_days = e.value("typical_days", 0);
            adj_[edge.source_id].push_back(edges_.size());
            edges_.push_back(std::move(edge));
        }
    }

    // Parse event mappings
    if (doc.contains("event_mappings") && doc["event_mappings"].is_object()) {
        for (const auto& [event_type, sectors] : doc["event_mappings"].items()) {
            std::vector<EventEntry> entries;
            for (const auto& s : sectors) {
                EventEntry entry;
                entry.sector_id = s.value("sector", "");
                entry.score     = static_cast<float>(s.value("score", 0.0));
                entries.push_back(std::move(entry));
            }
            event_map_[event_type] = std::move(entries);
        }
    }

    loaded_ = true;
    spdlog::info("EventPropagator: loaded {} nodes, {} edges, {} event types from {}",
                 nodes_.size(), edges_.size(), event_map_.size(), json_path);
    return true;
}

std::vector<PropagationResult> EventPropagator::propagate_event(
    const std::string& event_type, int max_hop) const {
    if (!loaded_) return {};

    auto it = event_map_.find(event_type);
    if (it == event_map_.end()) {
        spdlog::warn("EventPropagator: unknown event type '{}'", event_type);
        return {};
    }

    std::unordered_map<std::string, PropagationResult> best;

    struct QueueItem {
        std::string sector_id;
        float score;
        int hop;
        std::string path;
        std::string relation;
        int typical_days;
    };

    std::deque<QueueItem> q;

    // Seed with primary event sectors (hop=1)
    for (const auto& entry : it->second) {
        const std::string& sid = entry.sector_id;
        auto sw_it = id_to_sw_.find(sid);
        if (sw_it == id_to_sw_.end()) continue;

        PropagationResult r;
        r.sector       = sw_it->second;
        r.score        = entry.score;
        r.hop          = 1;
        r.typical_days = 0;
        r.relation     = "primary";
        r.path         = event_type + " -> " + sid;

        auto existing = best.find(sid);
        if (existing == best.end() ||
            std::abs(entry.score) > std::abs(existing->second.score)) {
            best[sid] = r;
        }

        q.push_back({sid, entry.score, 1, r.path, "primary", 0});
    }

    // BFS for secondary propagation (hop >= 2)
    while (!q.empty()) {
        auto item = q.front();
        q.pop_front();

        if (item.hop >= max_hop) continue;

        auto adj_it = adj_.find(item.sector_id);
        if (adj_it == adj_.end()) continue;

        for (size_t edge_idx : adj_it->second) {
            const Edge& edge = edges_[edge_idx];
            float new_score = item.score * edge.weight *
                              static_cast<float>(edge.direction) * 0.6f;
            int new_hop = item.hop + 1;
            const std::string& tgt = edge.target_id;

            auto sw_it = id_to_sw_.find(tgt);
            if (sw_it == id_to_sw_.end()) continue;

            // Only update if this path gives a stronger signal
            auto existing = best.find(tgt);
            if (existing != best.end() &&
                std::abs(new_score) <= std::abs(existing->second.score)) {
                continue;
            }

            std::string new_path = item.path + " -> " + tgt;

            PropagationResult r;
            r.sector       = sw_it->second;
            r.score        = new_score;
            r.hop          = new_hop;
            r.typical_days = edge.typical_days;
            r.relation     = edge.relation;
            r.path         = new_path;
            best[tgt] = r;

            q.push_back({tgt, new_score, new_hop, new_path,
                         edge.relation, edge.typical_days});
        }
    }

    std::vector<PropagationResult> result;
    result.reserve(best.size());
    for (auto& [key, r] : best) {
        result.push_back(std::move(r));
    }
    std::sort(result.begin(), result.end(),
              [](const PropagationResult& a, const PropagationResult& b) {
                  return std::abs(a.score) > std::abs(b.score);
              });
    return result;
}

std::vector<std::string> EventPropagator::available_events() const {
    std::vector<std::string> events;
    events.reserve(event_map_.size());
    for (const auto& [k, v] : event_map_) {
        events.push_back(k);
    }
    std::sort(events.begin(), events.end());
    return events;
}

} // namespace trade
