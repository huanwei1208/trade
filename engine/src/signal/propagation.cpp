#include "trade/signal/propagation.h"
#include <algorithm>
#include <deque>
#include <fstream>
#include <sqlite3.h>
#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>
#include <array>
#include <unordered_map>

namespace trade {

namespace {

const std::array<std::pair<const char*, SWIndustry>, 31> kSectorIds = {{
    {"SW_Agriculture", SWIndustry::kAgriculture},
    {"SW_Mining", SWIndustry::kMining},
    {"SW_Chemical", SWIndustry::kChemical},
    {"SW_Steel", SWIndustry::kSteel},
    {"SW_NonFerrousMetal", SWIndustry::kNonFerrousMetal},
    {"SW_Electronics", SWIndustry::kElectronics},
    {"SW_Auto", SWIndustry::kAuto},
    {"SW_HouseholdAppliance", SWIndustry::kHouseholdAppliance},
    {"SW_FoodBeverage", SWIndustry::kFoodBeverage},
    {"SW_Textile", SWIndustry::kTextile},
    {"SW_LightManufacturing", SWIndustry::kLightManufacturing},
    {"SW_Medicine", SWIndustry::kMedicine},
    {"SW_Utilities", SWIndustry::kUtilities},
    {"SW_Transportation", SWIndustry::kTransportation},
    {"SW_RealEstate", SWIndustry::kRealEstate},
    {"SW_Commerce", SWIndustry::kCommerce},
    {"SW_SocialService", SWIndustry::kSocialService},
    {"SW_Banking", SWIndustry::kBanking},
    {"SW_NonBankFinancial", SWIndustry::kNonBankFinancial},
    {"SW_Construction", SWIndustry::kConstruction},
    {"SW_BuildingMaterial", SWIndustry::kBuildingMaterial},
    {"SW_MechanicalEquipment", SWIndustry::kMechanicalEquipment},
    {"SW_Defense", SWIndustry::kDefense},
    {"SW_Computer", SWIndustry::kComputer},
    {"SW_Media", SWIndustry::kMedia},
    {"SW_Telecom", SWIndustry::kTelecom},
    {"SW_Environment", SWIndustry::kEnvironment},
    {"SW_ElectricalEquipment", SWIndustry::kElectricalEquipment},
    {"SW_Beauty", SWIndustry::kBeauty},
    {"SW_Coal", SWIndustry::kCoal},
    {"SW_Petroleum", SWIndustry::kPetroleum},
}};

SWIndustry parse_sw_entity(const std::string& entity_id) {
    static const std::unordered_map<std::string, SWIndustry> ids = [] {
        std::unordered_map<std::string, SWIndustry> out;
        for (const auto& [name, sw] : kSectorIds) out.emplace(name, sw);
        return out;
    }();
    auto it = ids.find(entity_id);
    return (it == ids.end()) ? SWIndustry::kUnknown : it->second;
}

std::string sector_name_zh(SWIndustry sw) {
    switch (sw) {
        case SWIndustry::kAgriculture: return "农林牧渔";
        case SWIndustry::kMining: return "采掘";
        case SWIndustry::kChemical: return "化工";
        case SWIndustry::kSteel: return "钢铁";
        case SWIndustry::kNonFerrousMetal: return "有色金属";
        case SWIndustry::kElectronics: return "电子";
        case SWIndustry::kAuto: return "汽车";
        case SWIndustry::kHouseholdAppliance: return "家用电器";
        case SWIndustry::kFoodBeverage: return "食品饮料";
        case SWIndustry::kTextile: return "纺织服装";
        case SWIndustry::kLightManufacturing: return "轻工制造";
        case SWIndustry::kMedicine: return "医药生物";
        case SWIndustry::kUtilities: return "公用事业";
        case SWIndustry::kTransportation: return "交通运输";
        case SWIndustry::kRealEstate: return "房地产";
        case SWIndustry::kCommerce: return "商业贸易";
        case SWIndustry::kSocialService: return "社会服务";
        case SWIndustry::kBanking: return "银行";
        case SWIndustry::kNonBankFinancial: return "非银金融";
        case SWIndustry::kConstruction: return "建筑装饰";
        case SWIndustry::kBuildingMaterial: return "建筑材料";
        case SWIndustry::kMechanicalEquipment: return "机械设备";
        case SWIndustry::kDefense: return "国防军工";
        case SWIndustry::kComputer: return "计算机";
        case SWIndustry::kMedia: return "传媒";
        case SWIndustry::kTelecom: return "通信";
        case SWIndustry::kEnvironment: return "环保";
        case SWIndustry::kElectricalEquipment: return "电力设备";
        case SWIndustry::kBeauty: return "美容护理";
        case SWIndustry::kCoal: return "煤炭";
        case SWIndustry::kPetroleum: return "石油石化";
        default: return "未知";
    }
}

bool has_column(sqlite3* db, const char* table, const char* column) {
    std::string sql = "PRAGMA table_info(" + std::string(table) + ")";
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    bool found = false;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        const auto* name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        if (name && std::string(name) == column) {
            found = true;
            break;
        }
    }
    sqlite3_finalize(stmt);
    return found;
}

}  // namespace

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

bool EventPropagator::load_sqlite(const std::string& db_path) {
    sqlite3* db = nullptr;
    if (sqlite3_open(db_path.c_str(), &db) != SQLITE_OK) {
        spdlog::error("EventPropagator: cannot open sqlite db {}", db_path);
        if (db) sqlite3_close(db);
        return false;
    }

    const bool has_direction = has_column(db, "kg_relations", "direction");
    const bool has_typical_days = has_column(db, "kg_relations", "typical_days");
    const bool has_status = has_column(db, "kg_relations", "status");

    nodes_.clear();
    edges_.clear();
    id_to_sw_.clear();
    event_map_.clear();
    adj_.clear();

    for (const auto& [id, sw] : kSectorIds) {
        Node node;
        node.id = id;
        node.sw_code = sw;
        node.name_zh = sector_name_zh(sw);
        nodes_.push_back(node);
        id_to_sw_[node.id] = node.sw_code;
    }

    const std::string direction_sql = has_direction
        ? "COALESCE(direction, CASE WHEN weight < 0 THEN -1 ELSE 1 END)"
        : "CASE WHEN weight < 0 THEN -1 ELSE 1 END";
    const std::string lag_sql = has_typical_days ? "COALESCE(typical_days, 0)" : "0";
    const std::string status_clause = has_status ? "status = 'active' AND " : "";
    const std::string sql =
        "SELECT from_entity, to_entity, rel_type, ABS(weight) AS weight, " +
        direction_sql + " AS direction, " + lag_sql + " AS typical_days "
        "FROM kg_relations "
        "WHERE " + status_clause + "(valid_to IS NULL OR valid_to >= date('now')) "
        "ORDER BY rel_type, from_entity, ABS(weight) DESC";

    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        spdlog::error("EventPropagator: failed to prepare SQLite query for {}", db_path);
        sqlite3_close(db);
        return false;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        const auto* from_ptr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        const auto* to_ptr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        const auto* rel_ptr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        if (!from_ptr || !to_ptr || !rel_ptr) continue;

        const std::string from_entity = from_ptr;
        const std::string to_entity = to_ptr;
        const std::string rel_type = rel_ptr;
        const float weight = static_cast<float>(sqlite3_column_double(stmt, 3));
        const int direction = sqlite3_column_int(stmt, 4);
        const int typical_days = sqlite3_column_int(stmt, 5);

        const SWIndustry src_sw = parse_sw_entity(from_entity);
        const SWIndustry tgt_sw = parse_sw_entity(to_entity);
        if (rel_type == "event_map" && tgt_sw != SWIndustry::kUnknown) {
            event_map_[from_entity].push_back({to_entity, weight * static_cast<float>(direction)});
            continue;
        }
        if (src_sw == SWIndustry::kUnknown || tgt_sw == SWIndustry::kUnknown) {
            continue;
        }

        Edge edge;
        edge.source_id = from_entity;
        edge.target_id = to_entity;
        edge.relation = rel_type;
        edge.weight = weight;
        edge.direction = direction;
        edge.typical_days = typical_days;
        adj_[edge.source_id].push_back(edges_.size());
        edges_.push_back(std::move(edge));
    }

    sqlite3_finalize(stmt);
    sqlite3_close(db);

    loaded_ = !edges_.empty() || !event_map_.empty();
    spdlog::info(
        "EventPropagator: loaded {} nodes, {} edges, {} event types from sqlite {}",
        nodes_.size(), edges_.size(), event_map_.size(), db_path
    );
    return loaded_;
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
