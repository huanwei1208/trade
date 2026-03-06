#include "trade/storage/cloud_sync.h"

namespace trade {

bool CloudSync::delete_paths(const std::vector<std::string>& paths) {
    bool all_ok = true;
    for (const auto& p : paths) {
        if (!delete_path(p)) {
            all_ok = false;
        }
    }
    return all_ok;
}

} // namespace trade
