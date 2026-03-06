#pragma once

#include "trade/common/config.h"
#include <string>

namespace trade::app {

struct TrainRequest {
    std::string symbol;
    std::string model;
};

int run_train(const TrainRequest& request, const Config& config);

} // namespace trade::app
