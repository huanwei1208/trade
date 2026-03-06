#pragma once
#include "trade/common/types.h"
#include <string>
#include <unordered_map>
#include <vector>

namespace trade {

struct PropagationResult {
    SWIndustry sector = SWIndustry::kUnknown;
    float score = 0.0f;       // propagation score, signed (+benefit / -harm)
    int hop = 0;              // 1=direct, 2=second-order
    int typical_days = 0;     // expected propagation lag in trading days
    std::string relation;     // edge type
    std::string path;         // e.g. "event -> SW_Electronics -> SW_Computer"
};

// Loads a pre-built sector graph JSON and answers propagation queries.
class EventPropagator {
public:
    EventPropagator() = default;

    // Load sector graph from JSON. Returns false on failure.
    bool load(const std::string& json_path);

    // Returns true if graph is loaded and ready.
    bool ready() const { return loaded_; }

    // Propagate a named event type.
    // Returns all affected sectors sorted by |score| descending.
    std::vector<PropagationResult> propagate_event(
        const std::string& event_type, int max_hop = 2) const;

    // List available event types.
    std::vector<std::string> available_events() const;

private:
    struct Node {
        SWIndustry sw_code = SWIndustry::kUnknown;
        std::string name_zh;
        std::string id;        // e.g. "SW_Electronics"
    };

    struct Edge {
        std::string source_id;
        std::string target_id;
        std::string relation;
        float weight = 0.0f;
        int direction = 1;    // +1 or -1
        int typical_days = 0;
    };

    struct EventEntry {
        std::string sector_id;
        float score = 0.0f;
    };

    std::vector<Node> nodes_;
    std::vector<Edge> edges_;
    std::unordered_map<std::string, SWIndustry> id_to_sw_;
    std::unordered_map<std::string, std::vector<EventEntry>> event_map_;
    // adjacency: source_id -> list of edge indices
    std::unordered_map<std::string, std::vector<size_t>> adj_;
    bool loaded_ = false;
};

} // namespace trade
