#pragma once

#include "trade/cli/args.h"
#include "trade/common/config.h"

namespace trade::cli {

int cmd_features(const CliArgs& args, const Config& config);
int cmd_train(const CliArgs& args, const Config& config);
int cmd_predict(const CliArgs& args, const Config& config);
int cmd_risk(const CliArgs& args, const Config& config);
int cmd_backtest(const CliArgs& args, const Config& config);

int cmd_report(const CliArgs& args, const Config& config);

} // namespace trade::cli
