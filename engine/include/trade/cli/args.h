#pragma once

#include <string>

namespace trade::cli {

struct CliArgs {
    std::string command;
    std::string config_path = "config";
    std::string symbol;
    std::string start_date;
    std::string end_date;
    std::string model;
    std::string strategy;
    std::string output;
    std::string scale = "zscore";
    std::string role;
    std::string admin_token;
    bool verbose = false;
};

void print_usage();
CliArgs parse_args(int argc, char* argv[]);

} // namespace trade::cli
