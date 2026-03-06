#include "trade/common/config.h"
#include <cstdlib>
#include <filesystem>
#include <set>
#include <spdlog/spdlog.h>
#include <stdexcept>

namespace trade {
namespace {

YAML::Node merge_yaml(const YAML::Node& base, const YAML::Node& overlay) {
    if (!overlay || overlay.IsNull()) return base;
    if (!base || base.IsNull()) return overlay;

    if (!base.IsMap() || !overlay.IsMap()) {
        return overlay;
    }

    YAML::Node out(YAML::NodeType::Map);
    for (const auto& kv : base) {
        out[kv.first.Scalar()] = kv.second;
    }
    for (const auto& kv : overlay) {
        const std::string key = kv.first.Scalar();
        if (out[key] && out[key].IsMap() && kv.second.IsMap()) {
            out[key] = merge_yaml(out[key], kv.second);
        } else {
            out[key] = kv.second;
        }
    }
    return out;
}

YAML::Node load_yaml_with_includes(const std::filesystem::path& file_path,
                                   std::set<std::string>& visiting) {
    const auto canonical = std::filesystem::weakly_canonical(file_path).string();
    if (visiting.count(canonical)) {
        throw std::runtime_error("Recursive config include detected: " + canonical);
    }
    visiting.insert(canonical);

    YAML::Node raw = YAML::LoadFile(canonical);
    YAML::Node merged(YAML::NodeType::Map);

    if (raw["includes"] && raw["includes"].IsSequence()) {
        for (const auto& inc_node : raw["includes"]) {
            if (!inc_node.IsScalar()) continue;
            std::filesystem::path inc_path = inc_node.as<std::string>();
            if (inc_path.is_relative()) {
                inc_path = std::filesystem::path(canonical).parent_path() / inc_path;
            }
            YAML::Node inc_cfg = load_yaml_with_includes(inc_path, visiting);
            merged = merge_yaml(merged, inc_cfg);
        }
    }

    YAML::Node self_cfg(YAML::NodeType::Map);
    for (const auto& kv : raw) {
        const std::string key = kv.first.Scalar();
        if (key == "includes") continue;
        self_cfg[key] = kv.second;
    }

    visiting.erase(canonical);
    return merge_yaml(merged, self_cfg);
}

YAML::Node load_root_config(const std::string& path) {
    namespace fs = std::filesystem;
    fs::path p = path;
    if (fs::is_directory(p)) {
        p = p / "config.yaml";
    }
    if (!fs::exists(p)) {
        throw std::runtime_error("Config path not found: " + p.string());
    }
    std::set<std::string> visiting;
    return load_yaml_with_includes(p, visiting);
}

} // namespace

Config Config::load(const std::string& path) {
    Config cfg = defaults();
    try {
        YAML::Node root = load_root_config(path);

        if (auto n = root["data"]) {
            if (n["data_root"]) cfg.data.data_root = n["data_root"].as<std::string>();
            if (n["models_dir"]) cfg.data.models_dir = n["models_dir"].as<std::string>();
        }

        if (auto n = root["ingestion"]) {
            if (n["min_start_date"]) cfg.ingestion.min_start_date = n["min_start_date"].as<std::string>();
        }

        if (auto n = root["storage"]) {
            if (n["enabled"]) cfg.storage.enabled = n["enabled"].as<bool>();
            if (n["backend"]) cfg.storage.backend = n["backend"].as<std::string>();
            if (n["write_mode"]) cfg.storage.write_mode = n["write_mode"].as<std::string>();
            if (n["hot_days"]) cfg.storage.hot_days = n["hot_days"].as<int>();
            if (n["keep_local_cold_copy"]) {
                cfg.storage.keep_local_cold_copy = n["keep_local_cold_copy"].as<bool>();
            }
            if (n["mirror_hot_to_cloud"]) {
                cfg.storage.mirror_hot_to_cloud = n["mirror_hot_to_cloud"].as<bool>();
            }
            if (n["google_drive_key_file"]) {
                cfg.storage.google_drive_key_file = n["google_drive_key_file"].as<std::string>();
            }
            if (n["google_drive_folder_id"]) {
                cfg.storage.google_drive_folder_id = n["google_drive_folder_id"].as<std::string>();
            }
            if (n["google_drive_timeout_ms"]) {
                cfg.storage.google_drive_timeout_ms = n["google_drive_timeout_ms"].as<int>();
            }
            if (n["google_drive_retry_count"]) {
                cfg.storage.google_drive_retry_count = n["google_drive_retry_count"].as<int>();
            }
        }

        if (auto n = root["security"]) {
            if (n["default_role"]) cfg.security.default_role = n["default_role"].as<std::string>();
            if (n["admin_token"]) cfg.security.admin_token = n["admin_token"].as<std::string>();
        }

        if (auto n = root["backtest"]) {
            if (n["initial_capital"]) cfg.backtest.initial_capital = n["initial_capital"].as<double>();
            if (n["max_positions"]) cfg.backtest.max_positions = n["max_positions"].as<int>();
            if (n["min_positions"]) cfg.backtest.min_positions = n["min_positions"].as<int>();
        }


        // Environment variable fallbacks for secrets
        if (cfg.storage.google_drive_key_file.empty()) {
            if (const char* v = std::getenv("GOOGLE_DRIVE_KEY_FILE"))
                cfg.storage.google_drive_key_file = v;
        }
        if (cfg.storage.google_drive_folder_id.empty()) {
            if (const char* v = std::getenv("GOOGLE_DRIVE_FOLDER_ID"))
                cfg.storage.google_drive_folder_id = v;
        }
        if (cfg.security.admin_token.empty()) {
            if (const char* v = std::getenv("TRADE_ADMIN_TOKEN"))
                cfg.security.admin_token = v;
        }
        spdlog::info("Config loaded from {}", path);
    } catch (const std::exception& e) {
        spdlog::warn("Failed to load config from {}: {}, using defaults", path, e.what());
    }
    return cfg;
}

Config Config::defaults() {
    return Config{};
}

} // namespace trade
