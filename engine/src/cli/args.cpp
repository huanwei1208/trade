#include "trade/cli/args.h"

#include <cstdlib>
#include <iostream>
#include <string>

namespace trade::cli {

void print_usage() {
    std::cout << R"(
trade_cli - Quantitative Trading Decision Support System

Usage:
  trade_cli <command> [options]

Commands:
  features    Compute features for a symbol
  train       Train ML model
  predict     Generate predictions
  risk        Assess risk for a position
  backtest    Run backtest
  report      Generate decision report

Options:
  --config <path>       Config path (file or dir, default: config)
  --symbol <symbol>     Stock symbol(s), comma-separated (e.g., 600000.SH,000001.SZ)
  --start <date>        Start date (YYYY-MM-DD)
  --end <date>          End date (YYYY-MM-DD)
  --scale <mode>        Feature scaling: zscore|rank|none (features command)
  --model <name>        Model name (e.g., lgbm)
  --strategy <name>     Strategy name
  --output <path>       Output file path
  --role <level>        CLI role: user|admin (default from config/security)
  --admin-token <tok>   Admin token (or env TRADE_ADMIN_TOKEN)
  --verbose             Enable verbose logging
  --help                Show this help
)" << std::endl;
}

CliArgs parse_args(int argc, char* argv[]) {
    CliArgs args;
    if (argc < 2) return args;

    args.command = argv[1];

    for (int i = 2; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--config" && i + 1 < argc) args.config_path = argv[++i];
        else if (arg == "--symbol" && i + 1 < argc) args.symbol = argv[++i];
        else if (arg == "--start" && i + 1 < argc) args.start_date = argv[++i];
        else if (arg == "--end" && i + 1 < argc) args.end_date = argv[++i];
        else if (arg == "--scale" && i + 1 < argc) args.scale = argv[++i];
        else if (arg == "--model" && i + 1 < argc) args.model = argv[++i];
        else if (arg == "--strategy" && i + 1 < argc) args.strategy = argv[++i];
        else if (arg == "--output" && i + 1 < argc) args.output = argv[++i];
        else if (arg == "--role" && i + 1 < argc) args.role = argv[++i];
        else if (arg == "--admin-token" && i + 1 < argc) args.admin_token = argv[++i];
        else if (arg == "--verbose") args.verbose = true;
        else if (arg == "--help") {
            print_usage();
            std::exit(0);
        }
    }
    return args;
}

} // namespace trade::cli
