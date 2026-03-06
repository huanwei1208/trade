#include "trade/cli/args.h"
#include "trade/cli/commands.h"
#include "trade/common/config.h"
#include "trade/storage/parquet_reader.h"
#include "trade/storage/parquet_writer.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <optional>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <spdlog/spdlog.h>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using CommandHandler = int (*)(const trade::cli::CliArgs&, const trade::Config&);

enum class CommandAccessLevel {
    kUser = 0,
    kAdmin = 1,
};

struct CommandEntry {
    const char* name;
    CommandHandler handler;
    bool paused;
    const char* paused_message;
    CommandAccessLevel min_access;
};

constexpr CommandEntry kCommandRegistry[] = {
    {"features", trade::cli::cmd_features, false, nullptr, CommandAccessLevel::kUser},
    {"train", trade::cli::cmd_train, false, nullptr, CommandAccessLevel::kUser},
    {"predict", trade::cli::cmd_predict, false, nullptr, CommandAccessLevel::kUser},
    {"risk", trade::cli::cmd_risk, false, nullptr, CommandAccessLevel::kUser},
    {"backtest", trade::cli::cmd_backtest, false, nullptr, CommandAccessLevel::kUser},
    {"report", trade::cli::cmd_report, false, nullptr, CommandAccessLevel::kUser},
};

const CommandEntry* find_command(const std::string& name) {
    const auto it = std::find_if(std::begin(kCommandRegistry), std::end(kCommandRegistry),
                                 [&](const CommandEntry& entry) { return name == entry.name; });
    if (it == std::end(kCommandRegistry)) return nullptr;
    return it;
}

const char* access_name(CommandAccessLevel level) {
    return level == CommandAccessLevel::kAdmin ? "admin" : "user";
}

std::optional<CommandAccessLevel> parse_access_level(std::string level) {
    std::transform(level.begin(), level.end(), level.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    if (level == "user" || level == "basic" || level == "default") {
        return CommandAccessLevel::kUser;
    }
    if (level == "admin") {
        return CommandAccessLevel::kAdmin;
    }
    return std::nullopt;
}

CommandAccessLevel resolve_request_access(const trade::cli::CliArgs& args,
                                          const trade::Config& config) {
    std::string role = args.role;
    if (role.empty()) {
        if (const char* env_role = std::getenv("TRADE_CLI_ROLE")) {
            role = env_role;
        }
    }
    if (role.empty()) {
        role = config.security.default_role;
    }
    if (role.empty()) {
        role = "user";
    }
    auto parsed = parse_access_level(role);
    if (!parsed) {
        throw std::invalid_argument("Invalid role '" + role + "'. Use user|admin");
    }
    return *parsed;
}

std::string resolve_admin_token(const trade::cli::CliArgs& args) {
    if (!args.admin_token.empty()) return args.admin_token;
    if (const char* env_token = std::getenv("TRADE_ADMIN_TOKEN")) {
        return env_token;
    }
    return "";
}

} // namespace

int main(int argc, char* argv[]) {
    auto args = trade::cli::parse_args(argc, argv);
    if (args.command.empty() || args.command == "--help") {
        trade::cli::print_usage();
        return 0;
    }

    auto console = spdlog::stdout_color_mt("console");
    spdlog::set_default_logger(console);
    spdlog::set_level(args.verbose ? spdlog::level::debug : spdlog::level::info);

    trade::Config config;
    std::vector<std::string> config_search = {args.config_path};
#ifdef TRADE_SOURCE_DIR
    config_search.push_back(std::string(TRADE_SOURCE_DIR) + "/config/config.yaml");
#endif

    bool loaded = false;
    for (const auto& cp : config_search) {
        try {
            config = trade::Config::load(cp);
            loaded = true;
            break;
        } catch (...) {
        }
    }
    if (!loaded) {
        spdlog::debug("Config not found, using defaults");
        config = trade::Config::defaults();
    }

    if (!config.data.data_root.empty() && config.data.data_root[0] != '/') {
#ifdef TRADE_SOURCE_DIR
        config.data.data_root = std::string(TRADE_SOURCE_DIR) + "/" + config.data.data_root;
#endif
    }

    trade::ParquetStore::configure_runtime(config.data, config.storage);
    trade::ParquetReader::configure_runtime(config.data, config.storage);

    try {
        const CommandEntry* command = find_command(args.command);
        if (command) {
            if (command->paused) {
                spdlog::error("{}", command->paused_message ? command->paused_message : "Command is paused.");
                return 1;
            }
            if (!command->handler) {
                spdlog::error("Command '{}' has no handler bound", args.command);
                return 1;
            }

            CommandAccessLevel request_access = resolve_request_access(args, config);
            if (static_cast<int>(request_access) < static_cast<int>(command->min_access)) {
                spdlog::error(
                    "Command '{}' requires {} role. Current role: {}. "
                    "Use --role admin for elevated commands.",
                    args.command,
                    access_name(command->min_access),
                    access_name(request_access));
                return 1;
            }

            if (command->min_access == CommandAccessLevel::kAdmin &&
                !config.security.admin_token.empty()) {
                const std::string token = resolve_admin_token(args);
                if (token != config.security.admin_token) {
                    spdlog::error(
                        "Admin token verification failed for command '{}'. "
                        "Provide --admin-token or set TRADE_ADMIN_TOKEN.",
                        args.command);
                    return 1;
                }
            }
            return command->handler(args, config);
        }
        spdlog::error("Unknown command: {}", args.command);
        trade::cli::print_usage();
        return 1;
    } catch (const std::exception& e) {
        spdlog::error("Error: {}", e.what());
        return 1;
    }
}
